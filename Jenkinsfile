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
                        if (isUnix()) {
                            sh '''
                                aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin 300052334150.dkr.ecr.ap-south-1.amazonaws.com
                                docker pull 300052334150.dkr.ecr.ap-south-1.amazonaws.com/incidentiq:latest || true
                                docker build -t incidentiq:latest .
                                docker tag incidentiq:latest 300052334150.dkr.ecr.ap-south-1.amazonaws.com/incidentiq:latest
                                docker push 300052334150.dkr.ecr.ap-south-1.amazonaws.com/incidentiq:latest
                                aws ecs update-service --cluster incidentiq-cluster --service incidentiq-service --force-new-deployment --region ap-south-1
                            '''
                        } else {
                            bat '''
                                echo --- Building and pushing image to ECR ---
                                aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin 300052334150.dkr.ecr.ap-south-1.amazonaws.com
                                docker pull 300052334150.dkr.ecr.ap-south-1.amazonaws.com/incidentiq:latest || exit 0
                                docker build -t incidentiq:latest .
                                docker tag incidentiq:latest 300052334150.dkr.ecr.ap-south-1.amazonaws.com/incidentiq:latest
                                docker push 300052334150.dkr.ecr.ap-south-1.amazonaws.com/incidentiq:latest

                                echo --- Deploying via ECS update-service ---
                                aws ecs update-service --cluster incidentiq-cluster --service incidentiq-service --force-new-deployment --region ap-south-1
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
                            echo Waiting 120 seconds for container to start...
                            ping 127.0.0.1 -n 121 > nul
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
