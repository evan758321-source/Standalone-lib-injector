import os
import re
import uuid
import time
import shutil
import subprocess
import threading
import tempfile
from pathlib import Path
from flask import Flask, request, jsonify, send_file, render_template

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB

BASE_DIR = Path(__file__).parent
WORK_DIR = Path(tempfile.gettempdir()) / 'apk_jobs'
WORK_DIR.mkdir(exist_ok=True)

APKTOOL_JAR     = BASE_DIR / 'tools' / 'apktool.jar'
UBER_SIGNER_JAR = BASE_DIR / 'tools' / 'signer.jar'

jobs = {}

def job_log(jid, msg, level='info'):
    jobs[jid]['log'].append({'msg': msg, 'level': level})


def run_job(jid, apk_path, so_files):
    job     = jobs[jid]
    job_dir = WORK_DIR / jid
    decompiled      = job_dir / 'decompiled'
    output_unsigned = job_dir / 'output_unsigned.apk'
    output_final    = job_dir / 'patched_signed.apk'

    try:
        # 1. Decompile
        job_log(jid, '► Decompiling APK with apktool...', 'info')
        r = subprocess.run(
            ['java', '-jar', str(APKTOOL_JAR), 'd', str(apk_path),
             '-o', str(decompiled), '-f'],
            capture_output=True, text=True, timeout=300
        )
        if r.returncode != 0:
            job_log(jid, '✗ apktool decompile failed:', 'err')
            for line in (r.stderr or r.stdout).splitlines()[-20:]:
                job_log(jid, '  ' + line, 'err')
            job['status'] = 'failed'; return
        job_log(jid, '  Decompiled ✔', 'ok')

        # 2. Find UnityPlayerActivity.smali
        job_log(jid, '► Locating UnityPlayerActivity.smali...', 'info')
        smali_file = next(decompiled.rglob('UnityPlayerActivity.smali'), None)
        if not smali_file:
            job_log(jid, '✗ UnityPlayerActivity.smali not found — is this a Unity APK?', 'err')
            job['status'] = 'failed'; return
        job_log(jid, f'  Found: {smali_file.relative_to(decompiled)} ✔', 'ok')

        # 3. Patch smali
        job_log(jid, '► Patching onCreate...', 'info')
        text = smali_file.read_text(encoding='utf-8')
        pattern = re.compile(
            r'(\.method (?:protected|public) onCreate\(Landroid/os/Bundle;\)V'
            r'.*?)(\.locals\s+\d+)',
            re.DOTALL
        )
        m = pattern.search(text)
        if not m:
            job_log(jid, '✗ Could not find onCreate + .locals in smali!', 'err')
            job['status'] = 'failed'; return

        inject = '\n\n    # == SO Injector =='
        for name, _ in so_files:
            inject += (
                f'\n    const-string v0, "{name}"'
                f'\n    invoke-static {{v0}}, Ljava/lang/System;->loadLibrary(Ljava/lang/String;)V'
            )
        inject += '\n    # == /SO Injector =='

        patched = text[:m.end(2)] + inject + text[m.end(2):]
        smali_file.write_text(patched, encoding='utf-8')
        job_log(jid, '  Smali patched ✔', 'ok')

        # 4. Place .so files
        arm64 = decompiled / 'lib' / 'arm64-v8a'
        arm64.mkdir(parents=True, exist_ok=True)
        for name, so_path in so_files:
            dest = arm64 / f'lib{name}.so'
            shutil.copy2(so_path, dest)
            job_log(jid, f'  lib{name}.so → lib/arm64-v8a/ ✔', 'ok')

        # 5. Recompile
        job_log(jid, '► Recompiling APK...', 'info')
        r = subprocess.run(
            ['java', '-jar', str(APKTOOL_JAR), 'b', str(decompiled),
             '-o', str(output_unsigned)],
            capture_output=True, text=True, timeout=300
        )
        if r.returncode != 0:
            job_log(jid, '✗ apktool recompile failed:', 'err')
            for line in (r.stderr or r.stdout).splitlines()[-20:]:
                job_log(jid, '  ' + line, 'err')
            job['status'] = 'failed'; return
        job_log(jid, '  Recompiled ✔', 'ok')

        # Clean up decompiled folder now — no longer needed, frees space
        shutil.rmtree(decompiled, ignore_errors=True)

        # 6. Sign
        job_log(jid, '► Signing APK (debug key)...', 'info')
        sign_out = job_dir / 'signed_out'
        sign_out.mkdir(exist_ok=True)
        r = subprocess.run(
            ['java', '-jar', str(UBER_SIGNER_JAR),
             '--apks', str(output_unsigned),
             '--out', str(sign_out),
             '--allowResign'],
            capture_output=True, text=True, timeout=120
        )

        # uber-apk-signer outputs something like output_unsigned-aligned-debugSigned.apk
        signed_candidates = list(sign_out.glob('*.apk'))
        if signed_candidates:
            shutil.copy2(str(signed_candidates[0]), str(output_final))
            shutil.rmtree(sign_out, ignore_errors=True)
            output_unsigned.unlink(missing_ok=True)
            job['output_path'] = str(output_final)
            job['output_name'] = 'patched_signed.apk'
            job_log(jid, '  Signed ✔', 'ok')
        else:
            # Signing failed — deliver unsigned anyway
            job['output_path'] = str(output_unsigned)
            job['output_name'] = 'patched_unsigned.apk'
            job_log(jid, '⚠ Signing failed — delivering unsigned APK', 'info')
            job_log(jid, '  ' + (r.stderr or r.stdout)[:300], 'info')

        # Verify the output file actually exists before marking done
        out_path = Path(job['output_path'])
        if not out_path.exists():
            job_log(jid, f'✗ Output file missing: {out_path}', 'err')
            job['status'] = 'failed'; return

        job_log(jid, '✔ Done! APK ready to download.', 'ok')
        job['status'] = 'done'

    except subprocess.TimeoutExpired:
        job_log(jid, '✗ Process timed out.', 'err')
        job['status'] = 'failed'
    except Exception as e:
        import traceback
        job_log(jid, f'✗ Unexpected error: {e}', 'err')
        job_log(jid, traceback.format_exc()[-500:], 'err')
        job['status'] = 'failed'
    finally:
        # Only clean up source files, NOT the output
        try:
            apk_path.unlink(missing_ok=True)
            for _, p in so_files:
                p.unlink(missing_ok=True)
        except Exception:
            pass


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/inject', methods=['POST'])
def inject():
    apk  = request.files.get('apk')
    libs = request.files.getlist('libs')

    if not apk or not apk.filename.lower().endswith('.apk'):
        return jsonify({'error': 'Please upload a valid .apk file'}), 400
    if not libs:
        return jsonify({'error': 'Please upload at least one .so file'}), 400

    jid     = str(uuid.uuid4())
    job_dir = WORK_DIR / jid
    job_dir.mkdir(parents=True)

    apk_path = job_dir / 'input.apk'
    apk.save(str(apk_path))

    so_files = []
    for f in libs:
        safe = re.sub(r'[^\w.\-]', '_', f.filename)
        if not safe.lower().endswith('.so'):
            continue
        p = job_dir / safe
        f.save(str(p))
        name = re.sub(r'\.so$', '', safe, flags=re.IGNORECASE)
        name = re.sub(r'^lib', '', name, flags=re.IGNORECASE)
        so_files.append((name, p))

    if not so_files:
        return jsonify({'error': 'No valid .so files found'}), 400

    jobs[jid] = {'status': 'running', 'log': [], 'output_path': None, 'output_name': None}
    threading.Thread(target=run_job, args=(jid, apk_path, so_files), daemon=True).start()
    return jsonify({'job_id': jid})


@app.route('/status/<jid>')
def status(jid):
    if jid not in jobs:
        return jsonify({'error': 'Unknown job'}), 404
    j = jobs[jid]
    return jsonify({'status': j['status'], 'log': j['log']})


@app.route('/download/<jid>')
def download(jid):
    if jid not in jobs:
        return jsonify({'error': 'Job not found — server may have restarted'}), 404
    j = jobs[jid]
    if j['status'] != 'done':
        return jsonify({'error': 'Job not done yet'}), 400
    if not j['output_path']:
        return jsonify({'error': 'No output file — build may have failed'}), 500

    out_path = Path(j['output_path'])
    if not out_path.exists():
        return jsonify({'error': f'Output file missing from disk: {out_path.name}'}), 500

    # Schedule full cleanup 15s after download
    def _delete_after():
        time.sleep(15)
        shutil.rmtree(str(WORK_DIR / jid), ignore_errors=True)
        jobs.pop(jid, None)
    threading.Thread(target=_delete_after, daemon=True).start()

    return send_file(
        str(out_path),
        as_attachment=True,
        download_name=j['output_name'],
        mimetype='application/vnd.android.package-archive'
    )


# ─── Periodic cleanup ─────────────────────────────────────────────────────────
def _cleanup():
    while True:
        time.sleep(3600)
        cutoff = time.time() - 7200
        for jid in list(jobs):
            d = WORK_DIR / jid
            if d.exists() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                jobs.pop(jid, None)

threading.Thread(target=_cleanup, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
