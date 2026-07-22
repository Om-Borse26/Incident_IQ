import os
import subprocess
import json
import time

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

print("Fetching container instances...")
ci_json = run_cmd("aws ecs list-container-instances --cluster incidentiq-cluster")
try:
    ci_data = json.loads(ci_json)
    ci_arns = ci_data.get('containerInstanceArns', [])
    if not ci_arns:
        print("No container instances found!")
        exit(1)
        
    ci_arn = ci_arns[0]
    print(f"Found container instance: {ci_arn}")
    
    ci_desc_json = run_cmd(f"aws ecs describe-container-instances --cluster incidentiq-cluster --container-instances {ci_arn}")
    ci_desc = json.loads(ci_desc_json)
    ec2_instance_id = ci_desc['containerInstances'][0]['ec2InstanceId']
    print(f"EC2 Instance ID: {ec2_instance_id}")
    
    print("Sending SSM command to clear Docker space...")
    ssm_cmd = f"aws ssm send-command --instance-ids {ec2_instance_id} --document-name \"AWS-RunShellScript\" --parameters commands=\"docker system prune -a -f --volumes\""
    ssm_res = run_cmd(ssm_cmd)
    
    try:
        ssm_data = json.loads(ssm_res)
        command_id = ssm_data['Command']['CommandId']
        print(f"Command sent! Command ID: {command_id}")
        print("Waiting for command to complete...")
        time.sleep(5)
        
        for _ in range(5):
            status_json = run_cmd(f"aws ssm list-command-invocations --command-id {command_id} --details")
            status_data = json.loads(status_json)
            if status_data.get('CommandInvocations'):
                invoc = status_data['CommandInvocations'][0]
                print(f"Status: {invoc['Status']}")
                if invoc['Status'] in ['Success', 'Failed', 'Cancelled']:
                    print(f"Output:\n{invoc['CommandPlugins'][0]['Output']}")
                    break
            time.sleep(5)
            
    except Exception as e:
        print(f"Error parsing SSM response: {e}\nRaw output: {ssm_res}")

except Exception as e:
    print(f"Error: {e}")
