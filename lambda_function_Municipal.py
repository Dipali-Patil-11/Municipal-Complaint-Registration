import json
import base64
import uuid
import os
import boto3
import pymysql
import traceback

# ==========================
# AWS CONFIGURATION
# ==========================

BUCKET_NAME = "municipal-images-12345"
REGION = "ap-south-1"

# How long a submitted complaint's image link stays valid.
# Presigned URLs work even when the bucket has Block Public Access
# enabled (they don't rely on a public bucket policy), but they DO
# expire — the Lambda's execution role also needs s3:GetObject on
# this bucket for these links to work (PutObject alone isn't enough).
IMAGE_URL_EXPIRY_SECONDS = 7 * 24 * 60 * 60  # 7 days

# ==========================
# RDS CONFIGURATION
# Prefer environment variables if set (Lambda console -> Configuration
# -> Environment variables), falling back to these values so nothing
# breaks if they aren't set yet. Moving DB_PASSWORD out of source code
# and into an env var (or Secrets Manager) is strongly recommended.
# ==========================

DB_HOST = os.environ.get("DB_HOST", "municipal-db.ctwo0ykggtl9.ap-south-1.rds.amazonaws.com")
DB_NAME = os.environ.get("DB_NAME", "municipal_db")
DB_USER = os.environ.get("DB_USER", "admin")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "DipaliPatil")

# ==========================
# AWS CLIENTS
# ==========================

s3 = boto3.client("s3", region_name=REGION)
rekognition = boto3.client("rekognition", region_name=REGION)

# ==========================
# COMPLAINT CATEGORY RULES
# Kept in one place so preview mode and the real submit path can never
# drift out of sync with each other.
# ==========================

CATEGORY_KEYWORDS = {
    "Garbage": ["garbage", "trash", "waste", "plastic", "rubbish", "litter",
                "debris", "junk", "dump", "recycling"],
    "Pothole": ["pothole", "asphalt", "tarmac", "pavement", "crack",
                "gravel", "road", "highway", "path"],
    "Traffic": ["vehicle", "car", "bus", "truck", "traffic", "automobile",
                "transportation", "motorcycle", "van", "wheel"],
    "Street Light": ["street light", "streetlight", "lamp post", "lamppost",
                      "light pole", "lighting", "lamp", "light fixture",
                      "bulb", "pole"],
}


def categorize_labels(rekognition_labels):
    """
    rekognition_labels: the raw list from rekognition_response["Labels"],
    i.e. [{"Name": "Garbage", "Confidence": 98.2, ...}, ...]

    Instead of exact string matching and stopping at the first category
    that matches (which is order-dependent and brittle against label
    name variations like "Lamp Post" vs "Light Pole"), this scores every
    category by the confidence-weighted sum of its matching labels
    (case-insensitive substring match) and picks the strongest one.

    Note: Rekognition's generic label detection has no real concept of
    "pothole" or "broken streetlight" — it only reports generic objects
    and scenes (Road, Lamp, Vehicle, etc). This keyword approach is a
    best-effort mapping on top of that, not a purpose-built classifier.
    For reliable results, train a Rekognition Custom Labels model on
    your own pothole / streetlight / garbage photos instead.
    """
    label_names = [item["Name"] for item in rekognition_labels]

    category_scores = {category: 0.0 for category in CATEGORY_KEYWORDS}
    category_hits = {category: [] for category in CATEGORY_KEYWORDS}

    for item in rekognition_labels:
        name_lower = item["Name"].lower()
        for category, keywords in CATEGORY_KEYWORDS.items():
            if any(keyword in name_lower for keyword in keywords):
                category_scores[category] += item["Confidence"]
                category_hits[category].append(item["Confidence"])

    best_category = max(category_scores, key=category_scores.get)

    if category_scores[best_category] == 0:
        detected_type = "Unknown"
        matched_confidence = rekognition_labels[0]["Confidence"] if rekognition_labels else 0
    else:
        detected_type = best_category
        matched_confidence = max(category_hits[best_category])

    return detected_type, round(matched_confidence, 2), label_names


# ==========================
# DATABASE CONNECTION
# ==========================

def get_connection():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor
    )


# ==========================
# COMMON RESPONSE
# ==========================

def response(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS"
        },
        "body": json.dumps(body, default=str)
    }


# ==========================
# DETECT HTTP METHOD
# Supports REST API + HTTP API
# ==========================

def get_http_method(event):
    if "httpMethod" in event:
        return event["httpMethod"]

    if "requestContext" in event:
        rc = event["requestContext"]
        if "http" in rc:
            return rc["http"].get("method", "")

    return ""


# ==========================
# LAMBDA HANDLER
# ==========================

def lambda_handler(event, context):
    print("========== LAMBDA STARTED ==========")
    print(json.dumps(event))

    try:
        method = get_http_method(event)

        # ==========================
        # CORS
        # ==========================

        if method == "OPTIONS":
            print("OPTIONS Request")
            return response(200, {"message": "CORS Enabled"})

        # ==========================
        # EVENTBRIDGE
        # ==========================

        if event.get("source") == "aws.scheduler":
            print("========== EVENTBRIDGE ==========")

            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute("""
                SELECT
                    id,
                    name,
                    location,
                    description,
                    complaint_type,
                    detected_type,
                    confidence,
                    image_url,
                    status,
                    created_at
                FROM complaints
                WHERE created_at >= NOW() - INTERVAL 5 MINUTE
                ORDER BY created_at DESC
            """)

            complaints = cursor.fetchall()

            print("Complaints Found :", len(complaints))

            for c in complaints:
                print(c)

            cursor.close()
            connection.close()

            return response(200, {
                "success": True,
                "message": "EventBridge Triggered Successfully",
                "total": len(complaints),
                "complaints": complaints
            })

        # ==========================
        # GET REQUEST
        # Dashboard
        # ==========================

        if method == "GET":
            print("Dashboard Request")

            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute("""
                SELECT
                    id,
                    name,
                    phone,
                    location,
                    description,
                    complaint_type,
                    detected_type,
                    confidence,
                    labels,
                    image_url,
                    status,
                    created_at
                FROM complaints
                WHERE created_at >= NOW() - INTERVAL 5 MINUTE
                ORDER BY created_at DESC
            """)

            complaints = cursor.fetchall()

            cursor.close()
            connection.close()

            return response(200, {
                "success": True,
                "count": len(complaints),
                "complaints": complaints
            })

        # ==========================
        # POST REQUEST
        # ==========================

        if method == "POST":
            print("Complaint Registration Started")

            body = json.loads(event["body"])

            # ==========================
            # PREVIEW MODE
            # Runs detection only — no S3 save, no DB write.
            # ==========================

            if body.get("preview") is True:
                print("Preview Mode Request")

                image = body["image"]

                if image.startswith("data:image"):
                    image = image.split(",", 1)[1]

                image_bytes = base64.b64decode(image)

                preview_result = rekognition.detect_labels(
                    Image={"Bytes": image_bytes},
                    MaxLabels=10,
                    MinConfidence=70
                )

                preview_detected_type, preview_confidence, preview_labels = categorize_labels(
                    preview_result["Labels"]
                )

                return response(200, {
                    "success": True,
                    "detected_type": preview_detected_type,
                    "confidence": preview_confidence,
                    "labels": preview_labels
                })

            # ==========================
            # REAL SUBMISSION
            # complaint_type is NOT read from the client — it's set
            # below from Rekognition's own detected_type, straight after
            # detection runs. The client never decides its own category.
            # ==========================

            name = body["name"]
            phone = body["phone"]
            location = body["location"]
            description = body["description"]
            image = body["image"]

            # ==========================
            # IMAGE PROCESSING
            # ==========================

            print("Decoding Image...")

            if image.startswith("data:image"):
                image = image.split(",", 1)[1]

            image_bytes = base64.b64decode(image)
            filename = str(uuid.uuid4()) + ".jpg"

            print("Uploading Image To S3...")

            s3.put_object(
                Bucket=BUCKET_NAME,
                Key=filename,
                Body=image_bytes,
                ContentType="image/jpeg"
            )

            print("Image Uploaded Successfully")

            # Presigned URL instead of a raw public S3 link — works even
            # with Block Public Access enabled on the bucket. Requires
            # the Lambda execution role to have s3:GetObject on this
            # bucket (PutObject permission alone won't cover this).
            image_url = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": BUCKET_NAME, "Key": filename},
                ExpiresIn=IMAGE_URL_EXPIRY_SECONDS
            )

            # ==========================
            # AMAZON REKOGNITION
            # ==========================

            print("Detecting Labels...")

            rekognition_response = rekognition.detect_labels(
                Image={
                    "S3Object": {
                        "Bucket": BUCKET_NAME,
                        "Name": filename
                    }
                },
                MaxLabels=10,
                MinConfidence=70
            )

            detected_type, confidence, label_names = categorize_labels(
                rekognition_response["Labels"]
            )
            label_text = ",".join(label_names)

            # complaint_type = detected_type, exactly as intended —
            # the category stored is always what Rekognition found.
            complaint_type = detected_type

            print("Detected Labels :", label_text)
            print("Complaint Type :", complaint_type)
            print("Confidence :", confidence)

            # ==========================
            # STORE IN DATABASE
            # ==========================

            print("Connecting To RDS...")

            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS complaints(
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(100),
                    phone VARCHAR(20),
                    location VARCHAR(255),
                    description TEXT,
                    complaint_type VARCHAR(100),
                    detected_type VARCHAR(100),
                    confidence FLOAT,
                    labels TEXT,
                    image_url TEXT,
                    status VARCHAR(30) DEFAULT 'Pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            print("Table Ready")

            cursor.execute("""
                INSERT INTO complaints(
                    name,
                    phone,
                    location,
                    description,
                    complaint_type,
                    detected_type,
                    confidence,
                    labels,
                    image_url
                )
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                name,
                phone,
                location,
                description,
                complaint_type,
                detected_type,
                confidence,
                label_text,
                image_url
            ))

            complaint_id = cursor.lastrowid
            connection.commit()

            cursor.close()
            connection.close()

            print("Complaint Stored Successfully")

            return response(200, {
                "success": True,
                "message": "Complaint Registered Successfully",
                "complaint_id": complaint_id,
                "image_url": image_url,
                "complaint_type": complaint_type,
                "detected_type": detected_type,
                "confidence": confidence,
                "labels": label_names
            })

        # ==========================
        # UNSUPPORTED METHOD
        # ==========================

        return response(400, {
            "success": False,
            "message": "Unsupported Request"
        })

    except Exception as e:
        print("========== ERROR ==========")
        print(str(e))
        traceback.print_exc()

        return response(500, {
            "success": False,
            "message": str(e)
        })