
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "CAB_SECRET_KEY", "local-project-secret-key"
)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///cabbooking.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

ADMIN_EMAIL = os.environ.get("CAB_ADMIN_EMAIL", "admin@cabgo.local")
ADMIN_PASSWORD = os.environ.get("CAB_ADMIN_PASSWORD", "Admin@12345")

RIDE_STATUSES = ("Booked", "Confirmed", "Completed")


# -------------------- DATABASE MODELS --------------------

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)


class Driver(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    is_available = db.Column(db.Boolean, default=False, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp()
    )


class DriverAccount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    driver_id = db.Column(
        db.Integer,
        db.ForeignKey("driver.id"),
        nullable=True
    )


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User", backref="bookings")
    pickup = db.Column(db.String(200), nullable=False)
    destination = db.Column(db.String(200), nullable=False)
    distance = db.Column(db.Float, nullable=False)
    cab_type = db.Column(db.String(30), nullable=False)
    fare = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default="Booked", nullable=False)


# -------------------- LOGIN PROTECTION --------------------

def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view


def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapped_view


# -------------------- HOME --------------------

@app.route("/")
def home():
    if session.get("is_admin"):
        return redirect(url_for("admin_dashboard"))

    if "driver_account_id" in session:
        return redirect(url_for("driver_dashboard"))

    if "user_id" in session:
        return redirect(url_for("dashboard"))

    return redirect(url_for("login"))


# -------------------- CUSTOMER REGISTRATION --------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not name or not email or not password:
            flash("Please fill in all fields.")
        elif len(password) < 8:
            flash("Password must contain at least 8 characters.")
        elif password != confirm_password:
            flash("Passwords do not match.")
        elif User.query.filter_by(email=email).first():
            flash("An account with this email already exists.")
        else:
            user = User(
                name=name,
                email=email,
                password=generate_password_hash(password)
            )
            db.session.add(user)
            db.session.commit()

            flash("Registration successful. Please login.")
            return redirect(url_for("login"))

    return render_template("register.html")


# -------------------- CUSTOMER LOGIN --------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password):
            session.clear()
            session["user_id"] = user.id
            session["user_name"] = user.name
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.")

    return render_template("login.html")


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template(
        "dashboard.html",
        name=session["user_name"]
    )


# -------------------- CAB BOOKING --------------------

@app.route("/book", methods=["GET", "POST"])
@login_required
def book():
    if request.method == "POST":
        pickup = request.form.get("pickup", "").strip()
        destination = request.form.get("destination", "").strip()
        cab_type = request.form.get("cab_type", "")
        distance_text = request.form.get("distance", "")

        rates = {"Mini": 12, "Sedan": 16, "SUV": 22}
        base_fares = {"Mini": 50, "Sedan": 80, "SUV": 120}

        try:
            distance = float(distance_text)
        except (ValueError, TypeError):
            flash("Please enter a valid distance.")
            return redirect(url_for("book"))

        if not pickup or not destination:
            flash("Please enter both locations.")
        elif pickup.casefold() == destination.casefold():
            flash("Pickup and drop locations must be different.")
        elif not 0 < distance <= 5000:
            flash("Distance must be between 0 and 5000 km.")
        elif cab_type not in rates:
            flash("Please select a valid cab type.")
        else:
            fare = round(
                base_fares[cab_type] + distance * rates[cab_type],
                2
            )

            booking = Booking(
                user_id=session["user_id"],
                pickup=pickup,
                destination=destination,
                distance=distance,
                cab_type=cab_type,
                fare=fare
            )

            db.session.add(booking)
            db.session.commit()

            flash("Cab booked successfully.")
            return redirect(url_for("history"))

    return render_template("book.html")


# -------------------- BOOKING HISTORY --------------------

@app.route("/history")
@login_required
def history():
    bookings = Booking.query.filter_by(
        user_id=session["user_id"]
    ).order_by(Booking.id.desc()).all()

    return render_template("history.html", bookings=bookings)


# -------------------- CANCEL BOOKING --------------------

@app.route("/cancel/<int:booking_id>", methods=["POST"])
@login_required
def cancel_booking(booking_id):
    booking = Booking.query.filter_by(
        id=booking_id,
        user_id=session["user_id"]
    ).first_or_404()

    if booking.status == "Booked":
        booking.status = "Cancelled"
        db.session.commit()
        flash("Booking cancelled successfully.")
    else:
        flash("Only booked rides can be cancelled.")

    return redirect(url_for("history"))


# -------------------- AVAILABLE DRIVERS API --------------------

@app.route("/api/available-drivers")
@login_required
def available_drivers():
    drivers = Driver.query.filter_by(is_available=True).all()

    return {
        "drivers": [
            {
                "id": driver.id,
                "name": driver.name,
                "latitude": driver.latitude,
                "longitude": driver.longitude
            }
            for driver in drivers
            if driver.latitude is not None
            and driver.longitude is not None
        ]
    }


# -------------------- DRIVER GPS LOCATION API --------------------

@app.route("/api/driver/location", methods=["POST"])
def update_driver_location():
    if "driver_account_id" not in session:
        return {"error": "Driver login required."}, 401

    data = request.get_json(silent=True) or {}

    try:
        latitude = float(data.get("latitude"))
        longitude = float(data.get("longitude"))
    except (TypeError, ValueError):
        return {
            "error": "Valid latitude and longitude are required."
        }, 400

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return {"error": "Coordinates are out of range."}, 400

    driver = db.session.get(Driver, session.get("driver_id"))

    if driver is None:
        return {
            "error": "Driver account is not linked to a cab."
        }, 404

    driver.latitude = latitude
    driver.longitude = longitude
    driver.is_available = True

    db.session.commit()

    return {
        "message": "GPS location updated. You are now available."
    }


# -------------------- DRIVER REGISTRATION --------------------

@app.route("/driver/register", methods=["GET", "POST"])
def driver_register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or not password:
            flash("Please fill in all fields.")
        elif len(password) < 8:
            flash("Password must contain at least 8 characters.")
        elif DriverAccount.query.filter_by(email=email).first():
            flash("This driver email is already registered.")
        else:
            driver = Driver(name=name, is_available=False)
            db.session.add(driver)
            db.session.flush()

            account = DriverAccount(
                name=name,
                email=email,
                password=generate_password_hash(password),
                driver_id=driver.id
            )

            db.session.add(account)
            db.session.commit()

            flash("Driver registration successful. Please login.")
            return redirect(url_for("driver_login"))

    return render_template("driver_register.html")


# -------------------- DRIVER LOGIN --------------------

@app.route("/driver/login", methods=["GET", "POST"])
def driver_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        account = DriverAccount.query.filter_by(email=email).first()

        if account and check_password_hash(account.password, password):
            session.clear()
            session["driver_account_id"] = account.id
            session["driver_id"] = account.driver_id
            session["driver_name"] = account.name

            return redirect(url_for("driver_dashboard"))

        flash("Invalid driver email or password.")

    return render_template("driver_login.html")


# -------------------- DRIVER DASHBOARD --------------------

@app.route("/driver/dashboard")
def driver_dashboard():
    if "driver_account_id" not in session:
        return redirect(url_for("driver_login"))

    return render_template(
        "driver_dashboard.html",
        driver_name=session["driver_name"]
    )


# -------------------- DRIVER LOGOUT --------------------

@app.route("/driver/logout", methods=["POST"])
def driver_logout():
    if "driver_account_id" not in session:
        return redirect(url_for("driver_login"))

    driver = db.session.get(Driver, session.get("driver_id"))

    if driver:
        driver.is_available = False
        db.session.commit()

    session.clear()
    flash("Driver logged out successfully.")

    return redirect(url_for("driver_login"))


# -------------------- ADMIN LOGIN --------------------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if email == ADMIN_EMAIL.lower() and password == ADMIN_PASSWORD:
            session.clear()
            session["is_admin"] = True
            session["admin_email"] = ADMIN_EMAIL
            return redirect(url_for("admin_dashboard"))

        flash("Invalid admin email or password.")

    return render_template("admin_login.html")


# -------------------- ADMIN DASHBOARD --------------------

@app.route("/admin")
@admin_required
def admin_dashboard():
    return render_template(
        "admin.html",
        total_users=User.query.count(),
        total_bookings=Booking.query.count(),
        active_bookings=Booking.query.filter_by(status="Booked").count(),
        cancelled_bookings=Booking.query.filter_by(status="Cancelled").count()
    )


# -------------------- ADMIN BOOKINGS --------------------

@app.route("/admin/bookings")
@admin_required
def admin_bookings():
    bookings = Booking.query.order_by(Booking.id.desc()).all()

    return render_template(
        "admin_bookings.html",
        bookings=bookings,
        ride_statuses=RIDE_STATUSES
    )


# -------------------- UPDATE BOOKING STATUS --------------------

@app.route("/admin/booking/<int:booking_id>/status", methods=["POST"])
@admin_required
def update_booking_status(booking_id):
    booking = db.session.get(Booking, booking_id)

    if booking is None:
        flash("Booking not found.")
        return redirect(url_for("admin_bookings"))

    new_status = request.form.get("status", "")

    if new_status not in RIDE_STATUSES:
        flash("Invalid ride status.")
    elif booking.status == "Cancelled":
        flash("Cancelled rides cannot be updated.")
    else:
        booking.status = new_status
        db.session.commit()
        flash("Ride status updated successfully.")

    return redirect(url_for("admin_bookings"))


# -------------------- ADMIN LOGOUT --------------------

@app.route("/admin/logout")
@admin_required
def admin_logout():
    session.clear()
    flash("Admin logged out.")
    return redirect(url_for("admin_login"))


# -------------------- CUSTOMER LOGOUT --------------------

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for("login"))


# -------------------- CREATE DATABASE TABLES --------------------

with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=True)
