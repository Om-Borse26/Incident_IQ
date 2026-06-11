pipeline {
    agent any

    environment {
        // Environment variables for testing locally inside Jenkins
        APP_ENV = 'test'
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
                            echo "Using existing local venv to save time..."
                        '''
                    }
                }
            }
        }

        stage('Run Gate Tests') {
            steps {
                withCredentials([
                    string(credentialsId: 'GROQ_API_KEY', variable: 'GROQ_API_KEY'),
                    string(credentialsId: 'GEMINI_API_KEY', variable: 'GEMINI_API_KEY'),
                    string(credentialsId: 'LANGCHAIN_API_KEY', variable: 'LANGCHAIN_API_KEY')
                ]) {
                    script {
                        if (isUnix()) {
                            sh '''
                                . venv/bin/activate
                                pytest tests/test_api.py -v
                            '''
                        } else {
                            bat '''
                                call venv\\Scripts\\activate.bat
                                set PYTHONPATH=.
                                pytest tests/test_api.py -v
                            '''
                        }
                    }
                }
            }
        }

        stage('Approval Gate') {
            steps {
                timeout(time: 1, unit: 'DAYS') {
                    input message: 'Tests passed! Approve deployment to production?', ok: 'Deploy to Railway'
                }
            }
        }

        stage('Deploy to Production') {
            steps {
                withCredentials([
                    string(credentialsId: 'RAILWAY_TOKEN', variable: 'RAILWAY_TOKEN')
                ]) {
                    script {
                        if (isUnix()) {
                            sh '''
                                echo "Installing Railway CLI..."
                                curl -fsSL cli.new | sh
                                
                                echo "Triggering Railway deployment..."
                                railway up --detach
                            '''
                        } else {
                            bat '''
                                echo "Installing Railway CLI..."
                                call npm i -g @railway/cli
                                
                                echo "Triggering Railway deployment..."
                                call npx @railway/cli up --service Incident_IQ --detach
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
                            echo "Waiting 30 seconds for Railway container to build and start..."
                            sleep 30
                            
                            echo "Running health check against live production..."
                            curl --fail -s https://incidentiq-production-b6f3.up.railway.app/health || {
                                echo "HEALTH CHECK FAILED! Production deployment is unreachable or broken."
                                exit 1
                            }
                            echo "Health check passed. Deployment verified."
                        '''
                    } else {
                        bat '''
                            echo "Waiting 30 seconds for Railway container to build and start..."
                            timeout /t 30
                            
                            echo "Running health check against live production..."
                            curl --fail -s https://incidentiq-production-b6f3.up.railway.app/health || (
                                echo "HEALTH CHECK FAILED! Production deployment is unreachable or broken."
                                exit /b 1
                            )
                            echo "Health check passed. Deployment verified."
                        '''
                    }
                }
            }
        }
    }

    post {
        failure {
            echo "Pipeline failed. Please check the logs."
        }
        success {
            echo "Pipeline completed successfully."
        }
    }
}
