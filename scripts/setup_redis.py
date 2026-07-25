import boto3
import time
import os
from dotenv import load_dotenv

def setup_redis(cluster_id="incidentiq-redis"):
    load_dotenv()
    session = boto3.Session(
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        region_name=os.environ.get("AWS_REGION", "ap-south-1")
    )
    client = session.client('elasticache')
    
    print(f"Creating ElastiCache Redis cluster '{cluster_id}'...")
    try:
        client.create_cache_cluster(
            CacheClusterId=cluster_id,
            Engine='redis',
            CacheNodeType='cache.t3.micro',
            NumCacheNodes=1,
            # No SubnetGroupName specified, usually falls back to default VPC
        )
        print("Creation initiated. Waiting for available status (this can take 5-10 minutes)...")
    except client.exceptions.CacheClusterAlreadyExistsFault:
        print("Cluster already exists. Checking status...")
    except Exception as e:
        print(f"Error creating cluster: {e}")
        return

    while True:
        try:
            resp = client.describe_cache_clusters(CacheClusterId=cluster_id)
            cluster = resp['CacheClusters'][0]
            status = cluster['CacheClusterStatus']
            print(f"Current status: {status}")
            
            if status == 'available':
                endpoint = cluster.get('CacheNodes', [{}])[0].get('Endpoint', {})
                address = endpoint.get('Address', 'unknown')
                port = endpoint.get('Port', 6379)
                print(f"Cluster is READY!")
                print(f"Endpoint: {address}:{port}")
                
                # Append to .env
                env_str = f"\nREDIS_URL=redis://{address}:{port}\n"
                # check if REDIS_URL is already in .env
                with open(".env", "r") as f:
                    content = f.read()
                if "REDIS_URL" not in content:
                    with open(".env", "a") as f:
                        f.write(env_str)
                    print("Appended REDIS_URL to .env")
                else:
                    print("REDIS_URL already present in .env")
                break
            elif status in ['deleting', 'deleted', 'create-failed']:
                print("Cluster creation failed or was deleted.")
                break
                
            time.sleep(30)
        except Exception as e:
            print(f"Error checking status: {e}")
            break

if __name__ == '__main__':
    setup_redis()
