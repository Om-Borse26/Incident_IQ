import os
import subprocess
import json
import base64

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

print("Terminating the frozen instance...")
run_cmd("aws ec2 terminate-instances --instance-ids i-05c8d887e877635fa")

user_data = """#!/bin/bash
mkdir -p /home/ubuntu/data
chmod 777 /home/ubuntu/data
echo ECS_CLUSTER=incidentiq-cluster >> /etc/ecs/ecs.config
systemctl restart ecs
"""
b64_user_data = base64.b64encode(user_data.encode('utf-8')).decode('utf-8')

print("Fetching VPCs and Subnets...")
vpcs_json = run_cmd("aws ec2 describe-vpcs --filters Name=isDefault,Values=true")
vpcs = json.loads(vpcs_json).get('Vpcs', [])
vpc_id = vpcs[0]['VpcId']

subnets_json = run_cmd(f"aws ec2 describe-subnets --filters Name=vpc-id,Values={vpc_id}")
subnets = json.loads(subnets_json).get('Subnets', [])
subnet_id = subnets[0]['SubnetId']

print("Fetching Security Groups...")
sgs_json = run_cmd(f"aws ec2 describe-security-groups --filters Name=vpc-id,Values={vpc_id}")
sgs = json.loads(sgs_json).get('SecurityGroups', [])
sg_id = None
for sg in sgs:
    if 'ecs' in sg['GroupName'].lower() or 'incident' in sg['GroupName'].lower():
        sg_id = sg['GroupId']
        break
if not sg_id:
    sg_id = sgs[0]['GroupId']

print("Fetching IAM Profiles...")
iam_json = run_cmd("aws iam list-instance-profiles")
profiles = json.loads(iam_json).get('InstanceProfiles', [])
iam_arn = next((p['Arn'] for p in profiles if 'ecsInstance' in p['InstanceProfileName']), profiles[0]['Arn'])

print("Launching Official ECS Amazon Linux 2023 Instance without Swap...")
launch_cmd = f"""aws ec2 run-instances \
    --image-id ami-0023f89a947da7030 \
    --instance-type t3.micro \
    --key-name incidentiq-key \
    --subnet-id {subnet_id} \
    --security-group-ids {sg_id} \
    --iam-instance-profile Arn={iam_arn} \
    --user-data {b64_user_data} \
    --tag-specifications "ResourceType=instance,Tags=[{{Key=Name,Value=incidentiq-ecs-noswap}}]"
"""
res = run_cmd(launch_cmd)
try:
    data = json.loads(res)
    print(f"Success! New ECS Instance ID: {data['Instances'][0]['InstanceId']}")
except:
    print(res)
