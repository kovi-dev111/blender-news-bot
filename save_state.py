import os
import subprocess

def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Command failed: {cmd}")
        print(f"Error: {result.stderr}")
    return result.returncode == 0

# Настройка git
run_cmd('git config --global user.name "github-actions[bot]"')
run_cmd('git config --global user.email "github-actions[bot]@users.noreply.github.com"')

# Добавляем файл
run_cmd('git add posted.json')

# Проверяем есть ли изменения
result = subprocess.run('git diff --staged --quiet', shell=True, capture_output=True)
if result.returncode != 0:
    # Есть изменения — коммитим
    run_cmd('git commit -m "Update posted state"')
    run_cmd('git push')
    print("State saved successfully")
else:
    print("No changes to save")
