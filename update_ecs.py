import os
import subprocess
import json
from pathlib import Path

# Load credentials from .env manually to avoid dotenv dependency
env_vars = {}
with open('.env', 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, val = line.split('=', 1)
            env_vars[key.strip()] = val.strip()

# Set up environment for subprocess
env = os.environ.copy()
env['AWS_ACCESS_KEY_ID'] = env_vars.get('AWS_ACCESS_KEY_ID', '')
env['AWS_SECRET_ACCESS_KEY'] = env_vars.get('AWS_SECRET_ACCESS_KEY', '')
env['AWS_DEFAULT_REGION'] = env_vars.get('AWS_REGION', 'ap-south-1')

def run_cmd(cmd):
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, shell=True)
    if result.returncode != 0:
        print(f"Error running command: {cmd}\nOutput: {result.stderr}")
        exit(1)
    return result.stdout

print("Fetching task definition...")
task_def_json = run_cmd("aws ecs describe-task-definition --task-definition incidentiq")
data = json.loads(task_def_json)
task_def = data['taskDefinition']

# Remove fields not allowed in register-task-definition
for field in ['taskDefinitionArn', 'revision', 'status', 'requiresAttributes', 'compatibilities', 'registeredAt', 'registeredBy']:
    task_def.pop(field, None)

# Update health check
for container in task_def.get('containerDefinitions', []):
    if container.get('name') == 'incidentiq':
        if 'healthCheck' in container:
            container['healthCheck']['startPeriod'] = 300
            print("Updated startPeriod to 300 in existing healthCheck")
        else:
            print("No healthCheck found in container!")

# Write to temp file
with open('new_task_def.json', 'w') as f:
    json.dump(task_def, f)

print("Registering new task definition...")
new_task_json = run_cmd("aws ecs register-task-definition --cli-input-json file://new_task_def.json")
new_data = json.loads(new_task_json)
new_revision = new_data['taskDefinition']['revision']
print(f"Registered new revision: incidentiq:{new_revision}")

print("Updating service to use the new revision...")
update_res = run_cmd(f"aws ecs update-service --cluster incidentiq-cluster --service incidentiq-service --task-definition incidentiq:{new_revision} --force-new-deployment")
print(f"Service updated successfully to incidentiq:{new_revision}!")

try:
    os.remove('new_task_def.json')
except:
    pass
