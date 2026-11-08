import os
import subprocess

def run_cmd(cmd):
    subprocess.run(cmd, shell=True, capture_output=True)

run_cmd('git config --global user.name "github-actions[bot]"')
run_cmd('git config --global user.email "actions@github.com"')
run_cmd('git add posted.json')

result = subprocess.run('git diff --staged --quiet', shell=True, capture_output=True)
if result.returncode != 0:
    run_cmd('git commit -m "Update posted state"')
    run_cmd('git push')
