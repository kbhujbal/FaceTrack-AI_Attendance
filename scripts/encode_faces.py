#!/usr/bin/env python3
"""
Face Encoding Utility Script
Encodes student photos and stores embeddings in database

Usage:
    python encode_faces.py --student S001 --image photos/alice.jpg
    python encode_faces.py --batch photos/  # Encode entire folder
"""
import argparse
import face_recognition
import numpy as np
from pathlib import Path
import psycopg2
from typing import Optional
import sys


def encode_face(image_path: str) -> Optional[np.ndarray]:
    """
    Extract 128-d face embedding from image

    Args:
        image_path: Path to student photo

    Returns:
        Face encoding array or None if no face detected
    """
    try:
        # Load image
        image = face_recognition.load_image_file(image_path)

        # Detect faces
        face_locations = face_recognition.face_locations(image, model="hog")

        if not face_locations:
            print(f"❌ No face detected in {image_path}")
            return None

        if len(face_locations) > 1:
            print(f"⚠️  Multiple faces detected in {image_path}, using first one")

        # Encode face
        encodings = face_recognition.face_encodings(image, face_locations)

        if not encodings:
            print(f"❌ Failed to encode face in {image_path}")
            return None

        encoding = encodings[0]
        print(f"✓ Encoded face from {image_path} (128-d vector)")

        return encoding

    except Exception as e:
        print(f"❌ Error processing {image_path}: {e}")
        return None


def store_encoding(student_id: str, encoding: np.ndarray, db_url: str):
    """
    Store face encoding in database

    Args:
        student_id: Student identifier
        encoding: Face embedding (128-d)
        db_url: PostgreSQL connection string
    """
    try:
        # Convert numpy array to bytes
        encoding_bytes = encoding.tobytes()

        # Connect to database
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()

        # Update student record
        cursor.execute("""
            UPDATE students
            SET face_encoding = %s,
                face_encoding_version = 'v1.0',
                last_encoding_update = CURRENT_TIMESTAMP
            WHERE student_id = %s
            RETURNING first_name, last_name
        """, (encoding_bytes, student_id))

        result = cursor.fetchone()

        if result:
            first_name, last_name = result
            conn.commit()
            print(f"✓ Stored encoding for {student_id} ({first_name} {last_name})")
        else:
            print(f"❌ Student {student_id} not found in database")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"❌ Database error: {e}")


def encode_single(student_id: str, image_path: str, db_url: str):
    """Encode and store single student photo"""
    print(f"\n📸 Processing {student_id}...")

    encoding = encode_face(image_path)

    if encoding is not None:
        store_encoding(student_id, encoding, db_url)


def encode_batch(photos_dir: str, db_url: str):
    """
    Encode all photos in directory

    Expects filename format: S001.jpg, S002.png, etc.
    """
    photos_path = Path(photos_dir)

    if not photos_path.exists():
        print(f"❌ Directory not found: {photos_dir}")
        return

    image_files = list(photos_path.glob("S*.jpg")) + list(photos_path.glob("S*.png"))

    if not image_files:
        print(f"❌ No student photos found in {photos_dir}")
        print("Expected format: S001.jpg, S002.png, etc.")
        return

    print(f"\n📁 Found {len(image_files)} photos")

    success_count = 0
    for image_file in sorted(image_files):
        # Extract student ID from filename (e.g., S001.jpg → S001)
        student_id = image_file.stem

        encoding = encode_face(str(image_file))

        if encoding is not None:
            store_encoding(student_id, encoding, db_url)
            success_count += 1

    print(f"\n✅ Encoded {success_count}/{len(image_files)} photos successfully")


def verify_encoding(student_id: str, db_url: str):
    """Verify encoding was stored correctly"""
    try:
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                student_id,
                first_name,
                last_name,
                CASE
                    WHEN face_encoding IS NOT NULL THEN 'Yes'
                    ELSE 'No'
                END as has_encoding,
                face_encoding_version,
                last_encoding_update
            FROM students
            WHERE student_id = %s
        """, (student_id,))

        result = cursor.fetchone()

        if result:
            sid, fname, lname, has_enc, version, updated = result
            print(f"\n📊 Student: {sid} - {fname} {lname}")
            print(f"   Encoding stored: {has_enc}")
            print(f"   Version: {version}")
            print(f"   Last updated: {updated}")
        else:
            print(f"❌ Student {student_id} not found")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"❌ Error: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Encode student face photos and store in database"
    )

    parser.add_argument(
        "--student",
        help="Student ID (e.g., S001)"
    )

    parser.add_argument(
        "--image",
        help="Path to student photo"
    )

    parser.add_argument(
        "--batch",
        help="Directory containing student photos (S001.jpg, S002.png, etc.)"
    )

    parser.add_argument(
        "--verify",
        help="Verify encoding exists for student ID"
    )

    parser.add_argument(
        "--db",
        default="postgresql://user:password@localhost:5432/attendance_db",
        help="Database connection string"
    )

    args = parser.parse_args()

    # Validate arguments
    if args.verify:
        verify_encoding(args.verify, args.db)
    elif args.batch:
        encode_batch(args.batch, args.db)
    elif args.student and args.image:
        encode_single(args.student, args.image, args.db)
    else:
        parser.print_help()
        print("\nExamples:")
        print("  python encode_faces.py --student S001 --image photos/alice.jpg")
        print("  python encode_faces.py --batch photos/")
        print("  python encode_faces.py --verify S001")
        sys.exit(1)


if __name__ == "__main__":
    main()
