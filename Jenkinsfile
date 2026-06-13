pipeline {
    agent any

    environment {
        AWS_REGION      = 'ap-south-1'
        ECR_REPO        = '300052334150.dkr.ecr.ap-south-1.amazonaws.com/incidentiq'
        EC2_HOST        = '13.204.107.11'
        EC2_USER        = 'ec2-user'
        SSLIP_URL       = 'https://13-204-107-11.sslip.io'
        APP_ENV         = 'test'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Setup Environment') {
            steps {
                script {
                    if (isUnix()) {
                        sh '''
                            python3 -m venv venv
                            . venv/bin/activate
                            pip install -r requirements.txt
                        '''
                    } else {
                        bat '''
                            echo "Updating local venv dependencies..."
                            if not exist venv python -m venv venv
                            call venv\\Scripts\\activate.bat
                            pip install -r requirements.txt
                        '''
                    }
                }
            }
        }

        stage('Run Gate Tests') {
            steps {
                withCredentials([
                    string(credentialsId: 'GROQ_API_KEY',       variable: 'GROQ_API_KEY'),
                    string(credentialsId: 'GEMINI_API_KEY',     variable: 'GEMINI_API_KEY'),
                    string(credentialsId: 'LANGCHAIN_API_KEY',  variable: 'LANGCHAIN_API_KEY')
                ]) {
                    script {
                        if (isUnix()) {
                            sh '''
                                . venv/bin/activate
                                pytest tests/test_api.py -v --junitxml=test-results.xml
                            '''
                        } else {
                            bat '''
                                call venv\\Scripts\\activate.bat
                                set PYTHONPATH=.
                                pytest tests/test_api.py -v --junitxml=test-results.xml
                            '''
                        }
                    }
                }
            }
            post {
                always {
                    junit 'test-results.xml'
                }
            }
        }

        stage('Approval Gate') {
            steps {
                timeout(time: 1, unit: 'DAYS') {
                    input message: 'Tests passed! Approve deployment to AWS EC2?', ok: 'Deploy to AWS'
                }
            }
        }

        stage('Build & Push to ECR') {
            steps {
                withCredentials([
                    string(credentialsId: 'AWS_ACCESS_KEY_ID',     variable: 'AWS_ACCESS_KEY_ID'),
                    string(credentialsId: 'AWS_SECRET_ACCESS_KEY',  variable: 'AWS_SECRET_ACCESS_KEY'),
                    string(credentialsId: 'AWS_ACCOUNT_ID',         variable: 'AWS_ACCOUNT_ID')
                ]) {
                    script {
                        if (isUnix()) {
                            sh '''
                                echo "--- Logging into ECR ---"
                                aws ecr get-login-password --region ${AWS_REGION} | \
                                    docker login --username AWS --password-stdin ${ECR_REPO}

                                echo "--- Building Docker image ---"
                                docker build -t incidentiq:latest .

                                echo "--- Tagging image ---"
                                docker tag incidentiq:latest ${ECR_REPO}:latest
                                docker tag incidentiq:latest ${ECR_REPO}:${BUILD_NUMBER}

                                echo "--- Pushing to ECR ---"
                                docker push ${ECR_REPO}:latest
                                docker push ${ECR_REPO}:${BUILD_NUMBER}

                                echo "Image pushed: ${ECR_REPO}:${BUILD_NUMBER}"
                            '''
                        } else {
                            bat """
                                echo --- Logging into ECR ---
                                call venv\\\\Scripts\\\\activate.bat
                                python -c "import boto3, base64; client = boto3.client('ecr', region_name='%AWS_REGION%'); token = client.get_authorization_token()['authorizationData'][0]['authorizationToken']; print(base64.b64decode(token).decode('utf-8').split(':')[1])" | docker login --username AWS --password-stdin %ECR_REPO%

                                echo --- Building Docker image ---
                                docker build -t incidentiq:latest .

                                echo --- Tagging image ---
                                docker tag incidentiq:latest %ECR_REPO%:latest
                                docker tag incidentiq:latest %ECR_REPO%:%BUILD_NUMBER%

                                echo --- Pushing to ECR ---
                                docker push %ECR_REPO%:latest
                                docker push %ECR_REPO%:%BUILD_NUMBER%
                            """
                        }
                    }
                }
            }
        }

        stage('Deploy to EC2') {
            steps {
                withCredentials([
                    string(credentialsId: 'AWS_ACCESS_KEY_ID',     variable: 'AWS_ACCESS_KEY_ID'),
                    string(credentialsId: 'AWS_SECRET_ACCESS_KEY',  variable: 'AWS_SECRET_ACCESS_KEY'),
                    string(credentialsId: 'AWS_ACCOUNT_ID',         variable: 'AWS_ACCOUNT_ID'),
                    sshUserPrivateKey(
                        credentialsId:  'EC2_SSH_KEY',
                        keyFileVariable: 'EC2_KEY',
                        usernameVariable: 'EC2_USER_VAR'
                    )
                ]) {
                    script {
                        // Write the .env content inline
                        def envContent = """LLM_FALLBACK_ORDER=gemini,groq
GROQ_API_KEY=${env.GROQ_API_KEY ?: ''}
GROQ_MODEL=llama-3.3-70b-versatile
GEMINI_API_KEY=${env.GEMINI_API_KEY ?: ''}
GEMINI_MODEL=gemini-2.5-flash
GROQ_VALIDATOR_API_KEY=${env.GROQ_VALIDATOR_API_KEY ?: ''}
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://apac.api.smith.langchain.com
LANGCHAIN_API_KEY=${env.LANGCHAIN_API_KEY ?: ''}
LANGCHAIN_PROJECT=incidentiq
AWS_REGION=ap-south-1
AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}
AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
DATA_DIR=/data
"""
                        writeFile file: 'remote.env', text: envContent

                        if (isUnix()) {
                            sh """
                                echo "--- Delivering .env to EC2 ---"
                                scp -i ${EC2_KEY} -o StrictHostKeyChecking=no \
                                    remote.env ${EC2_USER}@${EC2_HOST}:/home/ec2-user/.env

                                echo "--- Pulling new image and restarting container on EC2 ---"
                                ssh -i ${EC2_KEY} -o StrictHostKeyChecking=no ${EC2_USER}@${EC2_HOST} '
                                    set -e
                                    echo "Logging into ECR on EC2..."
                                    aws ecr get-login-password --region ap-south-1 | \
                                        docker login --username AWS --password-stdin ${ECR_REPO}

                                    echo "Pulling latest image..."
                                    docker pull ${ECR_REPO}:latest

                                    echo "Stopping old container (if any)..."
                                    docker stop incidentiq 2>/dev/null || true
                                    docker rm   incidentiq 2>/dev/null || true

                                    echo "Starting new container..."
                                    docker run -d \
                                        --name incidentiq \
                                        --restart unless-stopped \
                                        --env-file /home/ec2-user/.env \
                                        -p 8080:8080 \
                                        -v /home/ec2-user/data:/data \
                                        ${ECR_REPO}:latest

                                    echo "Container started."
                                    docker ps --filter name=incidentiq
                                '
                            """
                        } else {
                            // Windows batch execution
                            bat """
                                echo --- Fixing SSH Key Permissions for Windows OpenSSH ---
                                icacls "%EC2_KEY%" /inheritance:r
                                icacls "%EC2_KEY%" /grant:r *S-1-5-18:F
                                icacls "%EC2_KEY%" /grant:r *S-1-5-32-544:F
                                icacls "%EC2_KEY%" /grant:r "%USERNAME%":F

                                echo --- Delivering .env to EC2 ---
                                scp -i "%EC2_KEY%" -o StrictHostKeyChecking=no remote.env %EC2_USER%@%EC2_HOST%:/home/ec2-user/.env

                                echo --- Pulling new image and restarting container on EC2 ---
                                ssh -i "%EC2_KEY%" -o StrictHostKeyChecking=no %EC2_USER%@%EC2_HOST% "aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin %ECR_REPO% && docker pull %ECR_REPO%:latest && docker stop incidentiq 2>nul || true && docker rm incidentiq 2>nul || true && docker run -d --name incidentiq --restart unless-stopped --env-file /home/ec2-user/.env -p 8080:8080 -v /home/ec2-user/data:/data %ECR_REPO%:latest"
                            """
                        }

                        // Clean up local env file so secrets are not left on disk
                        if (isUnix()) {
                            sh 'rm -f remote.env'
                        } else {
                            bat 'del remote.env'
                        }
                    }
                }
            }
        }

        stage('Post-Deploy Verification') {
            steps {
                withCredentials([
                    string(credentialsId: 'GROQ_API_KEY',    variable: 'GROQ_API_KEY'),
                    string(credentialsId: 'GEMINI_API_KEY',  variable: 'GEMINI_API_KEY'),
                    string(credentialsId: 'LANGCHAIN_API_KEY', variable: 'LANGCHAIN_API_KEY')
                ]) {
                    script {
                        sh """
                            echo "Waiting 30 seconds for container to start..."
                            sleep 30

                            echo "Running health check against ${SSLIP_URL}..."
                            curl --fail -s ${SSLIP_URL}/health || {
                                echo "HEALTH CHECK FAILED! EC2 deployment is unreachable or broken."
                                exit 1
                            }
                            echo "Health check passed. AWS deployment verified."
                        """
                    }
                }
            }
        }
    }

    // Global Post Actions
    post {
        always {
            echo "Pipeline execution finished."
        }
        success {
            echo "SUCCESS: Pipeline completed. Live at ${SSLIP_URL}"
        }
        failure {
            echo "FAILURE: The pipeline failed or was aborted."
        }
    }
}
