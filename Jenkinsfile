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
                    string(credentialsId: 'GROQ_API_KEY', variable: 'GROQ_API_KEY'),
                    string(credentialsId: 'GEMINI_API_KEY', variable: 'GEMINI_API_KEY'),
                    string(credentialsId: 'LANGCHAIN_API_KEY', variable: 'LANGCHAIN_API_KEY')
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
                    // This tells Jenkins to parse the XML file and create nice graphs
                    junit 'test-results.xml'
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
                                railway up --service Incident_IQ --detach
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
                            ping 127.0.0.1 -n 31 > nul
                            
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
    
    // Global Post Actions
    post {
        always {
            echo "Pipeline execution finished."
            // We could run 'cleanWs()' here to delete the workspace and save disk space
        }
        success {
            echo "✅ SUCCESS: The pipeline completed flawlessly!"
            // This is where you would put a Slack webhook or Email notification code
            // e.g., slackSend(color: 'good', message: "Deployment Successful!")
        }
        failure {
            echo "❌ FAILURE: The pipeline failed or was aborted."
            // e.g., slackSend(color: 'danger', message: "Build Broken! Please check Jenkins.")
            // e.g., emailext(subject: "Build Failed", body: "Please check Jenkins", to: "your-email@example.com")
        }
    }
}
