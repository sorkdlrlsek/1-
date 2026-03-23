import boto3
import json
import pymysql
import logging
import os
from flask import Flask, request, jsonify

app = Flask(__name__)

# 로그 설정
os.makedirs("/var/log/worldpay", exist_ok=True)
logging.basicConfig(
    filename="/var/log/worldpay/app.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger("worldpay")


def get_secret():
    client = boto3.client("secretsmanager", region_name="ap-northeast-2")
    response = client.get_secret_value(SecretId="worldpay/db/credentials")
    return json.loads(response["SecretString"])


def get_connection():
    secret = get_secret()
    return pymysql.connect(
        host=secret["host"],
        user=secret["username"],
        password=secret["password"],
        db=secret["dbname"],
        port=int(secret["port"]),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/users", methods=["POST"])
def create_user():
    data = request.get_json()
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (name, email, phone) VALUES (%s, %s, %s)",
                (data["name"], data["email"], data.get("phone", ""))
            )
        conn.commit()
        logger.info(f"[CREATE] user created: {data['email']}")
        return jsonify({"message": "created"}), 201
    except Exception as e:
        logger.error(f"[CREATE] error: {str(e)}")
        return jsonify({"message": str(e)}), 500
    finally:
        conn.close()


@app.route("/users", methods=["GET"])
def list_users():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users")
            users = cursor.fetchall()
        logger.info(f"[LIST] total users: {len(users)}")
        return jsonify(users), 200
    except Exception as e:
        logger.error(f"[LIST] error: {str(e)}")
        return jsonify({"message": str(e)}), 500
    finally:
        conn.close()


@app.route("/users/<int:user_id>", methods=["GET"])
def get_user(user_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
        if not user:
            return jsonify({"message": "not found"}), 404
        logger.info(f"[GET] user_id: {user_id}")
        return jsonify(user), 200
    except Exception as e:
        logger.error(f"[GET] error: {str(e)}")
        return jsonify({"message": str(e)}), 500
    finally:
        conn.close()


@app.route("/users/<int:user_id>", methods=["PUT"])
def update_user(user_id):
    data = request.get_json()
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET name=%s, email=%s, phone=%s WHERE id=%s",
                (data["name"], data["email"], data.get("phone", ""), user_id)
            )
        conn.commit()
        logger.info(f"[UPDATE] user_id: {user_id}")
        return jsonify({"message": "updated"}), 200
    except Exception as e:
        logger.error(f"[UPDATE] error: {str(e)}")
        return jsonify({"message": str(e)}), 500
    finally:
        conn.close()


@app.route("/users/<int:user_id>", methods=["DELETE"])
def delete_user(user_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        logger.info(f"[DELETE] user_id: {user_id}")
        return jsonify({"message": "deleted"}), 200
    except Exception as e:
        logger.error(f"[DELETE] error: {str(e)}")
        return jsonify({"message": str(e)}), 500
    finally:
        conn.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
