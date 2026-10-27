import os
import sqlite3
from datetime import datetime

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    send_from_directory,
    abort
)

from werkzeug.utils import secure_filename


# -------------------------------
# APPLICATION CONFIGURATION
# -------------------------------

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
DB_PATH = os.path.join(BASE_DIR, "cu_notes.db")

ALLOWED_EXTENSIONS = {"pdf"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "change-this-secret-key-before-deploying"
)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# -------------------------------
# DATABASE CONNECTION
# -------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# -------------------------------
# CREATE DATABASE TABLE
# -------------------------------

def init_db():

    with get_db() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS notes (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                title TEXT NOT NULL,

                course TEXT NOT NULL,

                department TEXT NOT NULL,

                semester TEXT NOT NULL,

                author TEXT NOT NULL,

                description TEXT DEFAULT '',

                filename TEXT NOT NULL,

                original_filename TEXT NOT NULL,

                created_at TEXT NOT NULL

            )
        """)

        conn.commit()


# -------------------------------
# VALIDATE PDF FILE
# -------------------------------

def allowed_file(filename):

    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in ALLOWED_EXTENSIONS
    )


# -------------------------------
# HOME PAGE
# -------------------------------

@app.route("/")
def index():

    q = request.args.get("q", "").strip()

    course = request.args.get("course", "").strip()

    with get_db() as conn:

        sql = "SELECT * FROM notes WHERE 1=1"

        params = []

        if q:

            sql += """
                AND (
                    title LIKE ?
                    OR course LIKE ?
                    OR author LIKE ?
                    OR description LIKE ?
                )
            """

            like = f"%{q}%"

            params.extend([
                like,
                like,
                like,
                like
            ])

        if course:

            sql += " AND course LIKE ?"

            params.append(f"%{course}%")

        sql += " ORDER BY id DESC"

        notes = conn.execute(
            sql,
            params
        ).fetchall()

        courses = conn.execute("""
            SELECT DISTINCT course
            FROM notes
            ORDER BY course
        """).fetchall()

    return render_template(
        "index.html",
        notes=notes,
        q=q,
        course=course,
        courses=courses
    )


# -------------------------------
# UPLOAD NOTE
# -------------------------------

@app.route("/upload", methods=["GET", "POST"])
def upload():

    if request.method == "POST":

        title = request.form.get(
            "title", ""
        ).strip()

        course = request.form.get(
            "course", ""
        ).strip()

        department = request.form.get(
            "department", ""
        ).strip()

        semester = request.form.get(
            "semester", ""
        ).strip()

        author = request.form.get(
            "author", ""
        ).strip()

        description = request.form.get(
            "description", ""
        ).strip()

        file = request.files.get("note_file")


        # Check required fields

        if not all([
            title,
            course,
            department,
            semester,
            author
        ]):

            flash(
                "সব প্রয়োজনীয় তথ্য পূরণ করো।",
                "error"
            )

            return redirect(url_for("upload"))


        # Check uploaded file

        if not file or file.filename == "":

            flash(
                "একটি PDF ফাইল নির্বাচন করো।",
                "error"
            )

            return redirect(url_for("upload"))


        if not allowed_file(file.filename):

            flash(
                "শুধু PDF ফাইল আপলোড করা যাবে।",
                "error"
            )

            return redirect(url_for("upload"))


        # Generate a safe, unique filename

        original = secure_filename(file.filename)

        unique_name = (
            datetime.now().strftime("%Y%m%d%H%M%S%f")
            + "_"
            + original
        )

        save_path = os.path.join(
            UPLOAD_FOLDER,
            unique_name
        )

        file.save(save_path)


        # Basic PDF signature check

        with open(save_path, "rb") as saved:

            if not saved.read(5).startswith(b"%PDF-"):

                os.remove(save_path)

                flash(
                    "ফাইলটি সঠিক PDF নয়।",
                    "error"
                )

                return redirect(url_for("upload"))


        # Save note information to database

        with get_db() as conn:

            conn.execute("""
                INSERT INTO notes (

                    title,
                    course,
                    department,
                    semester,
                    author,
                    description,
                    filename,
                    original_filename,
                    created_at

                )

                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)

            """, (

                title,
                course,
                department,
                semester,
                author,
                description,
                unique_name,
                original,
                datetime.now().strftime(
                    "%Y-%m-%d %H:%M"
                )

            ))

            conn.commit()


        flash(
            "নোট সফলভাবে আপলোড হয়েছে!",
            "success"
        )

        return redirect(url_for("index"))


    return render_template("upload.html")


# -------------------------------
# NOTE DETAILS PAGE
# -------------------------------

@app.route("/note/<int:note_id>")
def note_detail(note_id):

    with get_db() as conn:

        note = conn.execute(
            "SELECT * FROM notes WHERE id = ?",
            (note_id,)
        ).fetchone()


    if not note:

        abort(404)


    return render_template(
        "detail.html",
        note=note
    )


# -------------------------------
# DOWNLOAD PDF
# -------------------------------

@app.route("/download/<int:note_id>")
def download(note_id):

    with get_db() as conn:

        note = conn.execute(
            """
            SELECT filename, original_filename
            FROM notes
            WHERE id = ?
            """,
            (note_id,)
        ).fetchone()


    if not note:

        abort(404)


    return send_from_directory(

        app.config["UPLOAD_FOLDER"],

        note["filename"],

        as_attachment=True,

        download_name=note["original_filename"]

    )


# -------------------------------
# FILE SIZE ERROR
# -------------------------------

@app.errorhandler(413)
def too_large(error):

    flash(
        "ফাইলটি ২০ MB-এর বেশি। ছোট PDF আপলোড করো।",
        "error"
    )

    return redirect(url_for("upload"))


# -------------------------------
# PAGE NOT FOUND
# -------------------------------

@app.errorhandler(404)
def not_found(error):

    return render_template("404.html"), 404


# -------------------------------
# INITIALIZE DATABASE
# -------------------------------

init_db()


# -------------------------------
# RUN WEBSITE
# -------------------------------

if __name__ == "__main__":

    app.run(debug=True)