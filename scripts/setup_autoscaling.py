import boto3
import sys

def setup_ecs_autoscaling(cluster_name="incidentiq-cluster", service_name="incidentiq-service"):
    print(f"Setting up auto-scaling for ECS Service: {service_name} in Cluster: {cluster_name}...")
    
    try:
        client = boto3.client('application-autoscaling', region_name='ap-south-1') # Assuming ap-south-1 based on previous interactions, update if different
    except Exception as e:
        print(f"Failed to initialize boto3 client: {e}")
        print("Please ensure you have AWS credentials configured.")
        return

    resource_id = f"service/{cluster_name}/{service_name}"
    
    try:
        print("1. Registering scalable target (Min: 1, Max: 4)...")
        client.register_scalable_target(
            ServiceNamespace='ecs',
            ResourceId=resource_id,
            ScalableDimension='ecs:service:DesiredCount',
            MinCapacity=1,
            MaxCapacity=4,
        )
        print("✅ Scalable target registered successfully.")

        print("2. Applying Target Tracking Scaling Policy (Target CPU: 60%)...")
        client.put_scaling_policy(
            PolicyName='incidentiq-cpu-scaling',
            ServiceNamespace='ecs',
            ResourceId=resource_id,
            ScalableDimension='ecs:service:DesiredCount',
            PolicyType='TargetTrackingScaling',
            TargetTrackingScalingPolicyConfiguration={
                'TargetValue': 60.0,
                'PredefinedMetricSpecification': {
                    'PredefinedMetricType': 'ECSServiceAverageCPUUtilization'
                },
                'ScaleOutCooldown': 60,
                'ScaleInCooldown': 300,
                'DisableScaleIn': False
            }
        )
        print("✅ Scaling policy applied successfully.")
        print("\n🎉 Auto-scaling is now active. Your ECS service will automatically scale out when CPU exceeds 60%, and scale in when demand drops.")
        
    except Exception as e:
        print(f"❌ Failed to configure auto-scaling: {e}")
        sys.exit(1)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Setup ECS Auto Scaling")
    parser.add_argument("--cluster", default="incidentiq-cluster", help="ECS Cluster Name")
    parser.add_argument("--service", default="incidentiq-service", help="ECS Service Name")
    parser.add_argument("--region", default="ap-south-1", help="AWS Region")
    args = parser.parse_args()
    
    # Update region before initializing client
    boto3.setup_default_session(region_name=args.region)
    setup_ecs_autoscaling(args.cluster, args.service)
