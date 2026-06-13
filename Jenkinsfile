pipeline {
    agent any

    environment {
        AWS_REGION      = 'ap-south-1'
        ECR_REPO        = '300052334150.dkr.ecr.ap-south-1.amazonaws.com/incidentiq'
        EC2_HOST        = '13.204.107.11'
        EC2_USER        = 'ubuntu'
        SSLIP_URL       = 'https://13-204-107-11.sslip.io'
        APP_ENV         = 'test'
        // Fixed path to SSH key (copied once, permissions set permanently)
        EC2_PEM         = 'C:\\ProgramData\\Jenkins\\.jenkins\\incidentiq-key.pem'
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
                            // Windows: use boto3 for ECR login (no AWS CLI installed locally)
                            bat '''
                                echo --- Logging into ECR ---
                                call venv\\Scripts\\activate.bat
                                python -c "import boto3, base64; client = boto3.client('ecr', region_name='ap-south-1'); token = client.get_authorization_token()['authorizationData'][0]['authorizationToken']; print(base64.b64decode(token).decode('utf-8').split(':')[1])" | docker login --username AWS --password-stdin 300052334150.dkr.ecr.ap-south-1.amazonaws.com/incidentiq

                                echo --- Building Docker image ---
                                docker build -t incidentiq:latest .

                                echo --- Tagging image ---
                                docker tag incidentiq:latest 300052334150.dkr.ecr.ap-south-1.amazonaws.com/incidentiq:latest
                                docker tag incidentiq:latest 300052334150.dkr.ecr.ap-south-1.amazonaws.com/incidentiq:%BUILD_NUMBER%

                                echo --- Pushing to ECR ---
                                docker push 300052334150.dkr.ecr.ap-south-1.amazonaws.com/incidentiq:latest
                                docker push 300052334150.dkr.ecr.ap-south-1.amazonaws.com/incidentiq:%BUILD_NUMBER%
                            '''
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
                    string(credentialsId: 'AWS_ACCOUNT_ID',         variable: 'AWS_ACCOUNT_ID')
                ]) {
                    script {
                        // Write .env file with all secrets
                        writeFile file: 'remote.env', text: """LLM_FALLBACK_ORDER=gemini,groq
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

                        if (isUnix()) {
                            sh '''
                                PEM_PATH="$HOME/.ssh/incidentiq-key.pem"
                                scp -i "$PEM_PATH" -o StrictHostKeyChecking=no \
                                    remote.env ubuntu@13.204.107.11:/home/ubuntu/.env

                                ssh -i "$PEM_PATH" -o StrictHostKeyChecking=no ubuntu@13.204.107.11 '
                                    set -e
                                    aws ecr get-login-password --region ap-south-1 | \
                                        docker login --username AWS --password-stdin 300052334150.dkr.ecr.ap-south-1.amazonaws.com/incidentiq
                                    docker pull 300052334150.dkr.ecr.ap-south-1.amazonaws.com/incidentiq:latest
                                    docker stop incidentiq 2>/dev/null || true
                                    docker rm   incidentiq 2>/dev/null || true
                                    docker run -d --name incidentiq \
                                        --restart unless-stopped \
                                        --env-file /home/ubuntu/.env \
                                        -p 8080:8080 \
                                        -v /home/ubuntu/data:/data \
                                        300052334150.dkr.ecr.ap-south-1.amazonaws.com/incidentiq:latest
                                    docker ps --filter name=incidentiq
                                '
                                rm -f remote.env
                            '''
                        } else {
                            // Windows: use the fixed PEM path with proper permissions
                            bat '''
                                echo --- Delivering .env to EC2 ---
                                scp -i "C:\\ProgramData\\Jenkins\\.jenkins\\incidentiq-key.pem" -o StrictHostKeyChecking=no remote.env ubuntu@13.204.107.11:/home/ubuntu/.env

                                echo --- Deploying container on EC2 ---
                                ssh -i "C:\\ProgramData\\Jenkins\\.jenkins\\incidentiq-key.pem" -o StrictHostKeyChecking=no ubuntu@13.204.107.11 "aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin 300052334150.dkr.ecr.ap-south-1.amazonaws.com/incidentiq && docker pull 300052334150.dkr.ecr.ap-south-1.amazonaws.com/incidentiq:latest && (docker stop incidentiq 2>/dev/null || true) && (docker rm incidentiq 2>/dev/null || true) && docker run -d --name incidentiq --restart unless-stopped --env-file /home/ubuntu/.env -p 8080:8080 -v /home/ubuntu/data:/data 300052334150.dkr.ecr.ap-south-1.amazonaws.com/incidentiq:latest && docker ps --filter name=incidentiq"

                                echo --- Cleaning up ---
                                del remote.env
                            '''
                        }
                    }
                }
            }
        }

        stage('Post-Deploy Verification') {
            steps {
                script {
                    if (isUnix()) {
                        sh '''
                            echo "Waiting 30 seconds for container to start..."
                            sleep 30
                            echo "Running health check..."
                            curl --fail -s https://13-204-107-11.sslip.io/health || {
                                echo "HEALTH CHECK FAILED!"
                                exit 1
                            }
                            echo "Health check passed."
                        '''
                    } else {
                        bat '''
                            echo Waiting 30 seconds for container to start...
                            ping 127.0.0.1 -n 31 > nul
                            echo Running health check...
                            curl --fail -s https://13-204-107-11.sslip.io/health || (
                                echo HEALTH CHECK FAILED!
                                exit /b 1
                            )
                            echo Health check passed.
                        '''
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
            echo "SUCCESS: Pipeline completed. Live at https://13-204-107-11.sslip.io"
        }
        failure {
            echo "FAILURE: The pipeline failed or was aborted."
        }
    }
}
