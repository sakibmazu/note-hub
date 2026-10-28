import os
import io
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
    send_file,
)
from werkzeug.utils import secure_filename
from supabase import create_client


# ==========================================
# CONFIGURATION
# ==========================================

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

BUCKET_NAME = "notes-pdf"
MAX_FILE_SIZE = 20 * 1024 * 1024


DEFAULT_SEMESTERS = [
    {
        "name": "1st semester",
        "label": "1st Semester",
        "number": 1,
    },
    {
        "name": "2nd semester",
        "label": "2nd Semester",
        "number": 2,
    },
]


COURSES_BY_SEMESTER = {
    1: [
        "Macroeconomics",
        "Microeconomics",
        "Mathematics",
        "Economic History of Bangladesh",
        "Statistics",
        "Quantitative Techniques Lab",
    ],
    2: [
        "Microeconomics",
        "Macroeconomic Theory",
        "Mathematical Economics",
        "Statistics",
        "Functional and Communicative English",
        "Fundamentals of Computing",
        "Comprehensive",
    ],
}


# ==========================================
# FLASK APP
# ==========================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "local-development-secret-change-me",
)

app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE


if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "Supabase URL or key is missing. Check your .env file."
    )


supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ==========================================
# HELPER FUNCTIONS
# ==========================================

def allowed_file(filename):
    return (
        bool(filename)
        and "." in filename
        and filename.rsplit(".", 1)[1].lower() == "pdf"
    )


def get_all_notes():
    result = (
        supabase.table("notes")
        .select("*")
        .order("id", desc=True)
        .execute()
    )

    return result.data or []


def get_note_by_id(note_id):
    result = (
        supabase.table("notes")
        .select("*")
        .eq("id", note_id)
        .limit(1)
        .execute()
    )

    notes = result.data or []

    return notes[0] if notes else None


def normalize_text(value):
    return str(value or "").strip().casefold()


def get_semester_number(value):
    semester_text = normalize_text(value)

    if "semester" not in semester_text:
        return None

    if "1st semester" in semester_text:
        return 1

    if "2nd semester" in semester_text:
        return 2

    return None


def semester_matches(note_semester, selected_semester):
    selected_number = get_semester_number(selected_semester)
    note_number = get_semester_number(note_semester)

    if selected_number is not None:
        return note_number == selected_number

    return (
        normalize_text(note_semester)
        == normalize_text(selected_semester)
    )


def course_matches(note_course, selected_course):
    saved_course = normalize_text(note_course)
    chosen_course = normalize_text(selected_course)

    # Match the previous misspelling with the correct course name.
    if chosen_course == "mathematical economics":
        return saved_course in {
            "mathematical economics",
            "mathmatical economics",
        }

    return saved_course == chosen_course


# ==========================================
# HOMEPAGE
# ==========================================

@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    semester = request.args.get("semester", "").strip()
    course = request.args.get("course", "").strip()

    all_notes = get_all_notes()

    semesters = list(DEFAULT_SEMESTERS)

    notes = all_notes

    # Search notes.
    if q:
        search_term = normalize_text(q)

        searchable_fields = (
            "title",
            "course",
            "author",
            "description",
            "department",
            "semester",
        )

        notes = [
            note
            for note in notes
            if any(
                search_term in normalize_text(note.get(field))
                for field in searchable_fields
            )
        ]

    # Filter by semester.
    if semester:
        notes = [
            note
            for note in notes
            if semester_matches(
                note.get("semester"),
                semester,
            )
        ]

    # Show all courses, even if no notes exist.
    courses = []

    if semester:
        semester_number = get_semester_number(semester)

        course_names = COURSES_BY_SEMESTER.get(
            semester_number,
            [],
        )

        courses = [
            {"course": course_name}
            for course_name in course_names
        ]

    # Filter by course.
    if course:
        notes = [
            note
            for note in notes
            if course_matches(
                note.get("course"),
                course,
            )
        ]

    return render_template(
        "index.html",
        notes=notes,
        q=q,
        semester=semester,
        course=course,
        semesters=semesters,
        courses=courses,
    )


# ==========================================
# UPLOAD NOTES
# ==========================================

@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "GET":
        return render_template("upload.html")

    title = request.form.get("title", "").strip()
    course = request.form.get("course", "").strip()
    department = request.form.get("department", "").strip()
    semester = request.form.get("semester", "").strip()
    author = request.form.get("author", "").strip()
    description = request.form.get("description", "").strip()

    file = request.files.get("note_file")

    if not all([
        title,
        course,
        department,
        semester,
        author,
    ]):
        flash("সব প্রয়োজনীয় তথ্য পূরণ করো।", "error")
        return redirect(url_for("upload"))

    if not file or not file.filename:
        flash("একটি PDF ফাইল নির্বাচন করো।", "error")
        return redirect(url_for("upload"))

    if not allowed_file(file.filename):
        flash("শুধু PDF ফাইল আপলোড করা যাবে।", "error")
        return redirect(url_for("upload"))

    original_filename = secure_filename(file.filename)

    if not original_filename:
        flash("ফাইলের নাম সঠিক নয়।", "error")
        return redirect(url_for("upload"))

    file_bytes = file.read(MAX_FILE_SIZE + 1)

    if len(file_bytes) > MAX_FILE_SIZE:
        flash(
            "ফাইলটি ২০ MB-এর বেশি। ছোট PDF আপলোড করো।",
            "error",
        )
        return redirect(url_for("upload"))

    if not file_bytes.startswith(b"%PDF-"):
        flash("ফাইলটি সঠিক PDF নয়।", "error")
        return redirect(url_for("upload"))

    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%d%H%M%S%f"
    )

    storage_path = f"{timestamp}_{original_filename}"
    uploaded = False

    try:
        # Upload PDF to Supabase Storage.
        supabase.storage.from_(BUCKET_NAME).upload(
            path=storage_path,
            file=file_bytes,
            file_options={
                "content-type": "application/pdf",
                "upsert": "false",
            },
        )

        uploaded = True

        file_url = (
            supabase.storage
            .from_(BUCKET_NAME)
            .get_public_url(storage_path)
        )

        created_at = datetime.now(timezone.utc).isoformat()

        # Save note details in the existing database.
        result = (
            supabase.table("notes")
            .insert({
                "title": title,
                "course": course,
                "department": department,
                "semester": semester,
                "author": author,
                "description": description,
                "filename": storage_path,
                "original_filename": original_filename,
                "file_url": file_url,
                "created_at": created_at,
            })
            .execute()
        )

        if not result.data:
            raise RuntimeError(
                "Database-এ নোট সংরক্ষণ হয়নি।"
            )

    except Exception:
        app.logger.exception("Note upload failed")

        if uploaded:
            try:
                supabase.storage.from_(BUCKET_NAME).remove(
                    [storage_path]
                )
            except Exception:
                app.logger.exception(
                    "Uploaded file cleanup failed"
                )

        flash(
            "আপলোড ব্যর্থ হয়েছে। "
            "Supabase-এর Database ও Storage Policy পরীক্ষা করো।",
            "error",
        )

        return redirect(url_for("upload"))

    flash("নোট সফলভাবে আপলোড হয়েছে!", "success")

    return redirect(url_for("index"))


# ==========================================
# NOTE DETAILS
# ==========================================

@app.route("/note/<int:note_id>")
def note_detail(note_id):
    note = get_note_by_id(note_id)

    if not note:
        abort(404)

    return render_template(
        "detail.html",
        note=note,
    )


# ==========================================
# DOWNLOAD PDF
# ==========================================

@app.route("/download/<int:note_id>")
def download(note_id):
    note = get_note_by_id(note_id)

    if not note:
        abort(404)

    storage_path = note.get("filename")

    if not storage_path:
        abort(404)

    try:
        file_bytes = (
            supabase.storage
            .from_(BUCKET_NAME)
            .download(storage_path)
        )

    except Exception:
        app.logger.exception("PDF download failed")
        abort(404)

    return send_file(
        io.BytesIO(file_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=(
            note.get("original_filename") or "note.pdf"
        ),
    )


# ==========================================
# ERROR HANDLERS
# ==========================================

@app.errorhandler(413)
def too_large(error):
    flash(
        "ফাইলটি ২০ MB-এর বেশি। ছোট PDF আপলোড করো।",
        "error",
    )

    return redirect(url_for("upload"))


@app.errorhandler(404)
def not_found(error):
    return render_template("404.html"), 404


# ==========================================
# RUN APPLICATION
# ==========================================

if __name__ == "__main__":
    app.run(debug=True)