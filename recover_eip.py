import os
import subprocess
import json
import time

def load_env():
    env_vars = {}
    if os.path.exists('.env'):
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    env_vars[key.strip()] = val.strip()
    return env_vars

env_vars = load_env()
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

EIP_ALLOCATION_ID = "eipalloc-0558377c9fc157618"
EIP_ADDRESS = "65.0.174.137"

print("Finding the running ECS instance in the Auto Scaling Group...")
instances_json = run_cmd('aws ec2 describe-instances --filters "Name=tag:aws:autoscaling:groupName,Values=incidentiq-asg" "Name=instance-state-name,Values=running"')
data = json.loads(instances_json)

instances = []
for res in data.get('Reservations', []):
    for inst in res.get('Instances', []):
        instances.append(inst['InstanceId'])

if not instances:
    print("No running instances found in the Auto Scaling Group!")
    exit(1)

instance_id = instances[0]
print(f"Found running ASG instance: {instance_id}")

print(f"Associating Elastic IP {EIP_ADDRESS} ({EIP_ALLOCATION_ID}) with instance {instance_id}...")
assoc_json = run_cmd(f"aws ec2 associate-address --instance-id {instance_id} --allocation-id {EIP_ALLOCATION_ID}")
assoc_data = json.loads(assoc_json)

print(f"Success! Associated with Association ID: {assoc_data.get('AssociationId')}")
print(f"\nThe backend is now reachable at: https://{EIP_ADDRESS.replace('.', '-')}.sslip.io")
