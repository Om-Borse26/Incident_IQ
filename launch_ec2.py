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

print("Fetching VPCs and Subnets...")
vpcs_json = run_cmd("aws ec2 describe-vpcs --filters Name=isDefault,Values=true")
vpcs = json.loads(vpcs_json).get('Vpcs', [])
if not vpcs:
    vpcs_json = run_cmd("aws ec2 describe-vpcs")
    vpcs = json.loads(vpcs_json).get('Vpcs', [])
vpc_id = vpcs[0]['VpcId']
print(f"Using VPC: {vpc_id}")

subnets_json = run_cmd(f"aws ec2 describe-subnets --filters Name=vpc-id,Values={vpc_id}")
subnets = json.loads(subnets_json).get('Subnets', [])
subnet_id = subnets[0]['SubnetId']
print(f"Using Subnet: {subnet_id}")

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
print(f"Using Security Group: {sg_id}")

print("Fetching IAM Profiles...")
iam_json = run_cmd("aws iam list-instance-profiles")
profiles = json.loads(iam_json).get('InstanceProfiles', [])
iam_arn = None
for p in profiles:
    if 'ecsInstanceRole' in p['InstanceProfileName']:
        iam_arn = p['Arn']
        break
if not iam_arn and profiles:
    iam_arn = profiles[0]['Arn']
print(f"Using IAM Profile: {iam_arn}")

user_data = """#!/bin/bash
if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo "Swap created!"
fi
echo ECS_CLUSTER=incidentiq-cluster >> /etc/ecs/ecs.config
systemctl restart docker
"""
import base64
b64_user_data = base64.b64encode(user_data.encode('utf-8')).decode('utf-8')

print("Launching Instance...")
launch_cmd = f"""aws ec2 run-instances \
    --image-id ami-0f58b397bc5c1f2e8 \
    --instance-type t3.micro \
    --key-name incidentiq-key \
    --subnet-id {subnet_id} \
    --security-group-ids {sg_id} \
    --iam-instance-profile Arn={iam_arn} \
    --user-data {b64_user_data} \
    --tag-specifications "ResourceType=instance,Tags=[{{Key=Name,Value=incidentiq}}]"
"""
res = run_cmd(launch_cmd)
print("Instance launched successfully!")
try:
    data = json.loads(res)
    print(f"New Instance ID: {data['Instances'][0]['InstanceId']}")
except:
    print(res)
