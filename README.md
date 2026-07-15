# Smart Municipal Complaint Portal

The Smart Municipal Complaint Portal is an AI-powered web application that allows citizens to register civic complaints (such as potholes, garbage, broken street lights, and traffic issues) quickly and efficiently. The portal utilizes **Amazon Rekognition** to automatically detect and categorize the issue from an uploaded photo, ensuring accurate routing and quick resolution.

## Architecture

This project is built using a serverless and highly scalable AWS architecture:
- **Frontend**: HTML/CSS/JS deployed on Amazon EC2 (using Apache) or S3.
- **Backend API**: AWS API Gateway and AWS Lambda.
- **Machine Learning**: Amazon Rekognition for image analysis and label detection.
- **Storage**: Amazon S3 for storing the uploaded complaint images.
- **Database**: Amazon RDS (MySQL) for storing complaint records securely.

## Features
- **AI-Powered Categorization**: Upload an image or capture a photo, and the AI automatically detects if it's a pothole, garbage, street light, or traffic issue.
- **Live Detection Preview**: Instantly see what the AI detects before submitting the complaint.
- **Real-time Dashboard**: View recent complaints with details like location, description, confidence score, and status.
- **Camera Integration**: Directly capture photos using a mobile or desktop camera.
- **Presigned URLs**: Secure access to uploaded images via temporary S3 presigned URLs.

## Project Structure
- `Municipal Web.html`: The frontend user interface for the complaint portal.
- `lambda_function_Municipal.py`: The AWS Lambda function containing backend logic (S3 upload, Rekognition detection, RDS database operations).
- `Database Commands in Cloudshell.txt`: Useful MySQL commands for managing the RDS database.
- `commands.txt`: Shell commands for deploying the frontend on an EC2 instance.
- `photos/`: Contains sample images of various complaint types.
- `screenshots/`: Contains screenshots of the web application and AWS setup.

## Setup Instructions

### 1. Database (Amazon RDS - MySQL)
1. Create an RDS MySQL instance.
2. Execute the table creation commands found in `lambda_function_Municipal.py` or `Database Commands in Cloudshell.txt` to initialize the `complaints` table.

### 2. Backend (AWS Lambda)
1. Create an S3 Bucket (e.g., `municipal-images-12345`) to store the images.
2. Create an AWS Lambda function using Python 3.x.
3. Attach an IAM role to the Lambda function with permissions for:
   - Amazon S3 (`PutObject`, `GetObject`)
   - Amazon Rekognition (`DetectLabels`)
   - AWS Lambda Basic Execution Role
4. Upload `lambda_function_Municipal.py` code to your Lambda function.
5. Set up Environment Variables for RDS credentials (`DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`).
6. Deploy an API Gateway and integrate it with your Lambda function to get the API Endpoint URL.

### 3. Frontend Deployment (Amazon EC2)
1. Launch an EC2 instance (Ubuntu).
2. Connect to your instance via SSH.
3. Install Apache:
   ```bash
   sudo apt update
   sudo apt install apache2 -y
   ```
4. Update `API_URL` in `Municipal Web.html` with your actual API Gateway endpoint.
5. Copy `Municipal Web.html` to `/var/www/html/index.html`:
   ```bash
   sudo nano /var/www/html/index.html
   ```
6. Restart Apache:
   ```bash
   sudo systemctl restart apache2
   ```

## Preview
For a demonstration of the platform, please check the `screenshots/` directory for visuals of the deployed web portal.
