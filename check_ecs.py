import os
import subprocess
import json

env_vars = {}
with open('.env', 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, val = line.split('=', 1)
            env_vars[key.strip()] = val.strip()

env = os.environ.copy()
env['AWS_ACCESS_KEY_ID'] = env_vars.get('AWS_ACCESS_KEY_ID', '')
env['AWS_SECRET_ACCESS_KEY'] = env_vars.get('AWS_SECRET_ACCESS_KEY', '')
env['AWS_DEFAULT_REGION'] = env_vars.get('AWS_REGION', 'ap-south-1')

def run_cmd(cmd):
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, shell=True)
    return result.stdout

print("=== SERVICE STATUS ===")
print(run_cmd("aws ecs describe-services --cluster incidentiq-cluster --services incidentiq-service --query \"services[0].[status, pendingCount, runningCount, taskDefinition]\""))

print("\n=== RECENT EVENTS ===")
events_json = run_cmd("aws ecs describe-services --cluster incidentiq-cluster --services incidentiq-service")
try:
    events = json.loads(events_json)['services'][0]['events']
    for e in events[:5]:
        print(f"[{e['createdAt']}] {e['message']}")
except:
    pass

print("\n=== RUNNING/PENDING TASKS ===")
tasks_json = run_cmd("aws ecs list-tasks --cluster incidentiq-cluster --service-name incidentiq-service")
tasks_data = json.loads(tasks_json) if tasks_json.strip() else {}
task_arns = tasks_data.get('taskArns', [])

if task_arns:
    arns_str = ' '.join(task_arns)
    details = run_cmd(f"aws ecs describe-tasks --cluster incidentiq-cluster --tasks {arns_str}")
    try:
        tasks = json.loads(details)['tasks']
        for t in tasks:
            print(f"Task: {t.get('taskArn')}")
            print(f"  Status: {t.get('lastStatus')} (Health: {t.get('healthStatus')})")
            print(f"  Definition: {t.get('taskDefinitionArn')}")
            print(f"  StopCode: {t.get('stopCode')} - {t.get('stoppedReason')}")
    except:
        pass
else:
    print("No active tasks found.")

print("\n=== STOPPED TASKS (Last 3) ===")
stopped_tasks_json = run_cmd("aws ecs list-tasks --cluster incidentiq-cluster --desired-status STOPPED --max-items 3")
stopped_data = json.loads(stopped_tasks_json) if stopped_tasks_json.strip() else {}
stopped_arns = stopped_data.get('taskArns', [])
if stopped_arns:
    arns_str = ' '.join(stopped_arns)
    details = run_cmd(f"aws ecs describe-tasks --cluster incidentiq-cluster --tasks {arns_str}")
    try:
        tasks = json.loads(details)['tasks']
        for t in tasks:
            print(f"Task: {t.get('taskArn')}")
            print(f"  Status: {t.get('lastStatus')}")
            print(f"  Definition: {t.get('taskDefinitionArn')}")
            print(f"  StopCode: {t.get('stopCode')} - {t.get('stoppedReason')}")
    except:
        pass
else:
    print("No stopped tasks found.")
