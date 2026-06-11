pipeline {
    agent any

    environment {
        // Environment variables for testing locally inside Jenkins
        AUTH_TOKEN = 'super-secret-key'
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
                sh '''
                    python3 -m venv venv
                    . venv/bin/activate
                    pip install -r requirements.txt
                '''
            }
        }

        stage('Run Gate Tests') {
            steps {
                withCredentials([
                    string(credentialsId: 'GROQ_API_KEY', variable: 'GROQ_API_KEY'),
                    string(credentialsId: 'GEMINI_API_KEY', variable: 'GEMINI_API_KEY'),
                    string(credentialsId: 'LANGCHAIN_API_KEY', variable: 'LANGCHAIN_API_KEY')
                ]) {
                    sh '''
                        . venv/bin/activate
                        pytest tests/test_api.py -v
                    '''
                }
            }
        }

        stage('Approval Gate') {
            when {
                branch 'main'
            }
            steps {
                timeout(time: 1, unit: 'DAYS') {
                    input message: 'Tests passed! Approve deployment to production?', ok: 'Deploy to Railway'
                }
            }
        }

        stage('Deploy to Production') {
            when {
                branch 'main'
            }
            steps {
                withCredentials([
                    string(credentialsId: 'RAILWAY_WEBHOOK', variable: 'RAILWAY_WEBHOOK_URL')
                ]) {
                    sh '''
                        echo "Triggering Railway deployment via Webhook..."
                        curl -X POST $RAILWAY_WEBHOOK_URL
                    '''
                }
            }
        }

        stage('Post-Deploy Verification') {
            when {
                branch 'main'
            }
            steps {
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
