# main.py - COMPLETE UPDATED VERSION

from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore, auth
from firebase_admin.firestore import firestore as firestore_client
import uuid
from datetime import datetime, timedelta, timezone
import pytz
import os   
import json


# --- Firebase Initialization ---
try:
    if os.path.exists("serviceAccountKey.json"):
        # Local development
        cred = credentials.Certificate("serviceAccountKey.json")
    else:
        # Production deployment
        firebase_config = {
            "type": os.environ.get("FIREBASE_TYPE"),
            "project_id": os.environ.get("FIREBASE_PROJECT_ID"),
            "private_key_id": os.environ.get("FIREBASE_PRIVATE_KEY_ID"),
            "private_key": os.environ.get("FIREBASE_PRIVATE_KEY").replace('\\n', '\n'),
            "client_email": os.environ.get("FIREBASE_CLIENT_EMAIL"),
            "client_id": os.environ.get("FIREBASE_CLIENT_ID"),
            "auth_uri": os.environ.get("FIREBASE_AUTH_URI"),
            "token_uri": os.environ.get("FIREBASE_TOKEN_URI")
        }
        cred = credentials.Certificate(firebase_config)
    
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("✅ Firebase connection successful.")
except Exception as e:
    print(f"🔥 Firebase connection failed: {e}")
    db = None

app = Flask(__name__)
CORS(app)

@app.route("/")
def index():
    return "Welcome to the Cholo Pay Backend!"

# --- USER REGISTRATION ---
@app.route("/register/user", methods=['POST'])
def register_user():
    if not db: 
        return jsonify({"error": "Database not initialized"}), 500
    
    try:
        data = request.get_json()
        user = auth.create_user(
            email=data['email'], 
            password=data['password'], 
            display_name=data['fullName']
        )
        
        user_ref = db.collection('users').document(user.uid)
        user_ref.set({
            'uid': user.uid, 
            'email': user.email, 
            'fullName': user.display_name, 
            'walletBalance': 500,  # Start with ₹500 for testing
            'createdAt': firestore_client.SERVER_TIMESTAMP
        })
        
        return jsonify({
            "success": True, 
            "message": "User registered successfully", 
            "uid": user.uid
        }), 201
        
    except Exception as e: 
        print(f"❌ User registration error: {e}")
        return jsonify({"error": str(e)}), 500

# --- USER LOGIN ---
@app.route("/login/user", methods=['POST'])
def login_user():
    try:
        data = request.get_json()
        user = auth.get_user_by_email(data['email'])
        custom_token = auth.create_custom_token(user.uid)
        
        return jsonify({
            "success": True, 
            "token": custom_token.decode('utf-8'), 
            "uid": user.uid
        })
        
    except Exception as e: 
        print(f"❌ User login error: {e}")
        return jsonify({"error": str(e)}), 500

# --- OWNER LOGIN ---
@app.route("/login/owner", methods=['POST'])
def login_owner():
    try:
        data = request.get_json()
        owner = auth.get_user_by_email(data['email'])
        custom_token = auth.create_custom_token(owner.uid)
        
        return jsonify({
            "success": True, 
            "token": custom_token.decode('utf-8'), 
            "uid": owner.uid
        })
        
    except Exception as e:
        print(f"❌ Owner login error: {e}")
        return jsonify({"error": str(e)}), 500

# --- OWNER REGISTRATION ---
@app.route("/register/owner", methods=['POST'])
def register_owner():
    try:
        data = request.get_json()
        
        owner = auth.create_user(
            email=data['email'], 
            password=data['password'], 
            display_name=data['fullName']
        )
        
        owner_ref = db.collection('owners').document(owner.uid)
        owner_ref.set({
            'uid': owner.uid, 
            'email': owner.email, 
            'fullName': owner.display_name, 
            'vehicleId': data['vehicleId'], 
            'fixedFare': int(data.get('fixedFare', 10)),
            'ticketValidityMinutes': 30,
            'totalEarnings': 0, 
            'createdAt': firestore_client.SERVER_TIMESTAMP
        })
        
        return jsonify({
            "success": True, 
            "message": "Owner registered successfully", 
            "uid": owner.uid
        }), 201
        
    except Exception as e: 
        print(f"❌ Owner registration error: {e}")
        return jsonify({"error": str(e)}), 500

# --- TRANSACTION HELPER FUNCTION ---
@firestore.transactional
def _run_payment_transaction(transaction, user_ref, owner_ref, fare):
    user_snapshot = user_ref.get(transaction=transaction)
    owner_snapshot = owner_ref.get(transaction=transaction)
    
    user_balance = user_snapshot.get('walletBalance')
    owner_earnings = owner_snapshot.get('totalEarnings')
    
    if user_balance < fare: 
        raise Exception("Insufficient funds")
    
    new_user_balance = user_balance - fare
    new_owner_earnings = owner_earnings + fare
    
    transaction.update(user_ref, {'walletBalance': new_user_balance})
    transaction.update(owner_ref, {'totalEarnings': new_owner_earnings})
    
    return new_user_balance

# --- GET USER DETAILS ---
@app.route("/get-user-details/<user_id>", methods=['GET'])
def get_user_details(user_id):
    if not db: 
        return jsonify({"error": "Database not initialized"}), 500
    
    try:
        print(f"🔍 Getting user details for: {user_id}")
        
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if user_doc.exists:
            user_data = user_doc.to_dict()
            print(f"✅ User found: {user_data.get('fullName', 'Unknown')}")
            
            # Ensure walletBalance exists and is a number
            if 'walletBalance' not in user_data:
                user_data['walletBalance'] = 0
                user_ref.update({'walletBalance': 0})
            
            # Convert any timestamps to serializable format
            for key, value in user_data.items():
                if hasattr(value, 'seconds'):  # Firestore timestamp
                    user_data[key] = {'seconds': value.seconds}
            
            return jsonify(user_data)
        else:
            print(f"❌ User not found: {user_id}")
            return jsonify({"error": "User not found"}), 404
            
    except Exception as e:
        print(f"❌ Get user details error: {e}")
        return jsonify({"error": str(e)}), 500

# --- GET USER TICKETS ---
@app.route("/get-user-tickets/<user_id>", methods=['GET'])
def get_user_tickets(user_id):
    if not db: 
        return jsonify({"error": "Database not initialized"}), 500
    
    try:
        print(f"🔍 Getting tickets for user: {user_id}")
        
        tickets = []
        current_time = datetime.now(pytz.UTC)
        
        # Get all tickets and filter by userId
        tickets_collection = db.collection('tickets')
        all_tickets = tickets_collection.stream()
        
        for ticket_doc in all_tickets:
            try:
                ticket_data = ticket_doc.to_dict()
                
                # Check if this ticket belongs to the user
                if ticket_data.get('userId') == user_id:
                    print(f"✅ Found ticket: {ticket_data.get('ticketId', 'Unknown')}")
                    
                    # Handle expiry time with proper timezone handling
                    expires_at = ticket_data.get('expiresAt')
                    
                    if expires_at:
                        try:
                            # Handle Firestore DatetimeWithNanoseconds
                            if hasattr(expires_at, 'timestamp'):
                                expires_at_aware = expires_at.replace(tzinfo=current_time.tzinfo) if expires_at.tzinfo is None else expires_at
                                current_time_aware = current_time.replace(tzinfo=expires_at.tzinfo) if current_time.tzinfo is None else current_time
                                
                                is_valid = current_time_aware < expires_at_aware and ticket_data.get('status', 'valid') == 'valid'
                                ticket_data['isValid'] = is_valid
                                ticket_data['timeRemaining'] = max(0, (expires_at_aware - current_time_aware).total_seconds()) if is_valid else 0
                                ticket_data['expiresAt'] = expires_at.isoformat()
                            else:
                                # Handle regular datetime objects
                                if isinstance(expires_at, datetime):
                                    is_valid = current_time < expires_at and ticket_data.get('status', 'valid') == 'valid'
                                    ticket_data['isValid'] = is_valid
                                    ticket_data['timeRemaining'] = max(0, (expires_at - current_time).total_seconds()) if is_valid else 0
                                    ticket_data['expiresAt'] = expires_at.isoformat()
                                else:
                                    ticket_data['isValid'] = ticket_data.get('status', 'valid') == 'valid'
                                    ticket_data['timeRemaining'] = 0
                        except Exception as e:
                            print(f"⚠️ Error processing expiry time: {e}")
                            ticket_data['isValid'] = ticket_data.get('status', 'valid') == 'valid'
                            ticket_data['timeRemaining'] = 0
                    else:
                        ticket_data['isValid'] = ticket_data.get('status', 'valid') == 'valid'
                        ticket_data['timeRemaining'] = 0
                    
                    # Handle timestamp with proper error handling
                    if 'timestamp' in ticket_data:
                        timestamp = ticket_data['timestamp']
                        try:
                            if hasattr(timestamp, 'seconds'):
                                ticket_data['timestamp'] = {'seconds': timestamp.seconds}
                            elif hasattr(timestamp, 'timestamp'):
                                ticket_data['timestamp'] = {'seconds': int(timestamp.timestamp())}
                        except Exception as e:
                            print(f"⚠️ Error processing timestamp: {e}")
                            ticket_data['timestamp'] = {'seconds': 0}
                    
                    # Ensure required fields exist
                    ticket_data.setdefault('ticketId', ticket_doc.id)
                    ticket_data.setdefault('vehicleId', 'Unknown')
                    ticket_data.setdefault('farePaid', 0)
                    ticket_data.setdefault('status', 'valid')
                    
                    tickets.append(ticket_data)
                    
            except Exception as e:
                print(f"⚠️ Error processing ticket: {e}")
                continue
        
        print(f"✅ Found {len(tickets)} tickets for user")
        
        # Sort by timestamp (newest first)
        try:
            tickets.sort(key=lambda x: x.get('timestamp', {}).get('seconds', 0), reverse=True)
        except Exception as e:
            print(f"⚠️ Error sorting tickets: {e}")
        
        return jsonify(tickets)
        
    except Exception as e:
        print(f"❌ Get user tickets error: {e}")
        return jsonify([])

# --- GET VEHICLE FARE ---
@app.route("/get-vehicle-fare/<vehicle_id>", methods=['GET'])
def get_vehicle_fare(vehicle_id):
    if not db: 
        return jsonify({"error": "Database not initialized"}), 500
    
    try:
        print(f"🔍 Looking for vehicle: {vehicle_id}")
        
        # Get all owners and find by vehicleId
        owners_collection = db.collection('owners')
        all_owners = owners_collection.stream()
        
        for owner_doc in all_owners:
            owner_data = owner_doc.to_dict()
            if owner_data.get('vehicleId') == vehicle_id:
                print(f"✅ Vehicle found: {vehicle_id}")
                
                fare = int(owner_data.get('fixedFare', 10))
                validity_minutes = int(owner_data.get('ticketValidityMinutes', 30))
                
                return jsonify({
                    "success": True,
                    "fare": fare,
                    "validityMinutes": validity_minutes,
                    "vehicleId": vehicle_id
                })
        
        print(f"❌ Vehicle not found: {vehicle_id}")
        return jsonify({"error": "Vehicle not found"}), 404
        
    except Exception as e:
        print(f"❌ Get vehicle fare error: {e}")
        return jsonify({"error": str(e)}), 500

# --- PAYMENT ENDPOINT ---
@app.route("/pay", methods=['POST'])
def make_payment():
    if not db: 
        return jsonify({"error": "Database not initialized"}), 500
    
    try:
        data = request.get_json()
        user_id = data['userId']
        vehicle_id = data['vehicleId']
        
        print(f"💳 Processing payment: User {user_id} -> Vehicle {vehicle_id}")
        
        # Find owner by vehicle ID
        owner_ref = None
        owner_data = None
        
        owners_collection = db.collection('owners')
        all_owners = owners_collection.stream()
        
        for owner_doc in all_owners:
            temp_data = owner_doc.to_dict()
            if temp_data.get('vehicleId') == vehicle_id:
                owner_ref = owners_collection.document(owner_doc.id)
                owner_data = temp_data
                break
        
        if not owner_data:
            return jsonify({"error": "Vehicle not found"}), 404
        
        fare = int(owner_data.get('fixedFare', 10))
        validity_minutes = int(owner_data.get('ticketValidityMinutes', 30))
        
        # Check user balance
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            return jsonify({"error": "User not found"}), 404
        
        user_data = user_doc.to_dict()
        user_balance = user_data.get('walletBalance', 0)
        
        if user_balance < fare:
            return jsonify({"error": "Insufficient funds"}), 400
        
        # Update balances
        new_user_balance = user_balance - fare
        new_owner_earnings = owner_data.get('totalEarnings', 0) + fare
        
        user_ref.update({'walletBalance': new_user_balance})
        owner_ref.update({'totalEarnings': new_owner_earnings})
        
        # Create ticket
        ticket_id = str(uuid.uuid4())
        current_time = datetime.now(pytz.UTC)
        expiry_time = current_time + timedelta(minutes=validity_minutes)
        
        ticket_ref = db.collection('tickets').document(ticket_id)
        ticket_ref.set({
            'ticketId': ticket_id,
            'userId': user_id,
            'ownerId': owner_ref.id,
            'vehicleId': vehicle_id,
            'farePaid': fare,
            'timestamp': firestore_client.SERVER_TIMESTAMP,
            'expiresAt': expiry_time,
            'status': 'valid'
        })
        
        print(f"✅ Payment successful: Ticket {ticket_id}")
        
        return jsonify({
            "success": True,
            "message": "Payment successful. Ticket generated.",
            "ticketId": ticket_id,
            "newBalance": new_user_balance,
            "farePaid": fare,
            "expiresAt": expiry_time.isoformat(),
            "validityMinutes": validity_minutes
        }), 201
        
    except Exception as e:
        print(f"❌ Payment error: {e}")
        return jsonify({"error": str(e)}), 500

# --- ADD FUNDS ---
@app.route("/add-funds", methods=['POST'])
def add_funds():
    try:
        data = request.get_json()
        user_id = data['userId']
        amount = int(data['amount'])
        
        if amount <= 0:
            return jsonify({"error": "Amount must be greater than 0"}), 400
        
        print(f"💰 Adding ₹{amount} to user: {user_id}")
        
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if user_doc.exists:
            current_balance = user_doc.to_dict().get('walletBalance', 0)
            new_balance = current_balance + amount
            user_ref.update({'walletBalance': new_balance})
            
            print(f"✅ Balance updated: ₹{current_balance} -> ₹{new_balance}")
            
            return jsonify({
                "success": True, 
                "message": f"Added ₹{amount} to wallet.",
                "newBalance": new_balance
            })
        else:
            return jsonify({"error": "User not found"}), 404
        
    except Exception as e:
        print(f"❌ Add funds error: {e}")
        return jsonify({"error": str(e)}), 500

# --- GET OWNER DETAILS ---
@app.route("/get-owner-details/<owner_id>", methods=['GET'])
def get_owner_details(owner_id):
    try:
        print(f"🔍 Getting owner details for: {owner_id}")
        
        owner_ref = db.collection('owners').document(owner_id)
        owner_doc = owner_ref.get()
        
        if owner_doc.exists:
            owner_data = owner_doc.to_dict()
            print(f"✅ Owner found: {owner_data.get('fullName', 'Unknown')}")
            
            # Convert timestamps
            for key, value in owner_data.items():
                if hasattr(value, 'seconds'):
                    owner_data[key] = {'seconds': value.seconds}
            
            return jsonify(owner_data)
        else:
            print(f"❌ Owner not found: {owner_id}")
            return jsonify({"error": "Owner not found"}), 404
            
    except Exception as e:
        print(f"❌ Get owner details error: {e}")
        return jsonify({"error": str(e)}), 500

# --- GET OWNER TICKETS ---
@app.route("/get-owner-tickets/<owner_id>", methods=['GET'])
def get_owner_tickets(owner_id):
    if not db: 
        return jsonify({"error": "Database not initialized"}), 500
    
    try:
        print(f"🔍 Getting tickets for owner: {owner_id}")
        
        tickets = []
        current_time = datetime.now()
        
        # Get all tickets and filter by ownerId
        tickets_collection = db.collection('tickets')
        all_tickets = tickets_collection.stream()
        
        for ticket_doc in all_tickets:
            try:
                ticket_data = ticket_doc.to_dict()
                
                # Check if this ticket belongs to the owner
                if ticket_data.get('ownerId') == owner_id:
                    print(f"✅ Found owner ticket: {ticket_data.get('ticketId', 'Unknown')}")
                    
                    # Get user details
                    user_id = ticket_data.get('userId')
                    if user_id:
                        try:
                            user_ref = db.collection('users').document(user_id)
                            user_doc = user_ref.get()
                            
                            if user_doc.exists:
                                user_data = user_doc.to_dict()
                                ticket_data['userName'] = user_data.get('fullName', 'Unknown User')
                                ticket_data['userEmail'] = user_data.get('email', 'No email')
                            else:
                                ticket_data['userName'] = 'Unknown User'
                                ticket_data['userEmail'] = 'No email'
                        except Exception as e:
                            print(f"⚠️ Error getting user details: {e}")
                            ticket_data['userName'] = 'Unknown User'
                            ticket_data['userEmail'] = 'No email'
                    else:
                        ticket_data['userName'] = 'Unknown User'
                        ticket_data['userEmail'] = 'No email'
                    
                    # Handle expiry time and validity
                    expires_at = ticket_data.get('expiresAt')
                    if expires_at:
                        try:
                            if hasattr(expires_at, 'timestamp'):
                                expires_at_aware = expires_at.replace(tzinfo=current_time.tzinfo) if expires_at.tzinfo is None else expires_at
                                current_time_aware = current_time.replace(tzinfo=expires_at.tzinfo) if current_time.tzinfo is None else current_time
                                
                                is_valid = current_time_aware < expires_at_aware and ticket_data.get('status', 'valid') == 'valid'
                                ticket_data['isValid'] = is_valid
                                ticket_data['isActive'] = is_valid
                                ticket_data['expiresAt'] = expires_at.isoformat()
                            else:
                                is_valid = ticket_data.get('status', 'valid') == 'valid'
                                ticket_data['isValid'] = is_valid
                                ticket_data['isActive'] = is_valid
                        except Exception as e:
                            print(f"⚠️ Error processing expiry: {e}")
                            ticket_data['isValid'] = ticket_data.get('status', 'valid') == 'valid'
                            ticket_data['isActive'] = ticket_data.get('status', 'valid') == 'valid'
                    else:
                        ticket_data['isValid'] = ticket_data.get('status', 'valid') == 'valid'
                        ticket_data['isActive'] = ticket_data.get('status', 'valid') == 'valid'
                    
                    # Handle timestamp
                    if 'timestamp' in ticket_data:
                        timestamp = ticket_data['timestamp']
                        try:
                            if hasattr(timestamp, 'seconds'):
                                ticket_data['timestamp'] = {'seconds': timestamp.seconds}
                            elif hasattr(timestamp, 'timestamp'):
                                ticket_data['timestamp'] = {'seconds': int(timestamp.timestamp())}
                        except Exception as e:
                            print(f"⚠️ Error processing timestamp: {e}")
                            ticket_data['timestamp'] = {'seconds': 0}
                    
                    # Ensure required fields
                    ticket_data.setdefault('ticketId', ticket_doc.id)
                    ticket_data.setdefault('vehicleId', 'Unknown')
                    ticket_data.setdefault('farePaid', 0)
                    ticket_data.setdefault('status', 'valid')
                    
                    tickets.append(ticket_data)
                    
            except Exception as e:
                print(f"⚠️ Error processing owner ticket: {e}")
                continue
        
        print(f"✅ Found {len(tickets)} tickets for owner")
        
        # Sort by timestamp (newest first)
        try:
            tickets.sort(key=lambda x: x.get('timestamp', {}).get('seconds', 0), reverse=True)
        except Exception as e:
            print(f"⚠️ Error sorting tickets: {e}")
        
        return jsonify(tickets)
        
    except Exception as e:
        print(f"❌ Get owner tickets error: {e}")
        return jsonify([])

# --- GET TICKETS BY STATUS ---
@app.route("/get-tickets-by-status/<owner_id>/<status>", methods=['GET'])
def get_tickets_by_status(owner_id, status):
    if not db: 
        return jsonify({"error": "Database not initialized"}), 500
    
    try:
        print(f"🔍 Getting {status} tickets for owner: {owner_id}")
        
        filtered_tickets = []
        current_time = datetime.now()
        
        # Get all tickets and filter by ownerId and status
        tickets_collection = db.collection('tickets')
        all_tickets = tickets_collection.stream()
        
        for ticket_doc in all_tickets:
            try:
                ticket_data = ticket_doc.to_dict()
                
                # Check if this ticket belongs to the owner
                if ticket_data.get('ownerId') == owner_id:
                    
                    # Determine if ticket is active or expired
                    expires_at = ticket_data.get('expiresAt')
                    if expires_at:
                        try:
                            if hasattr(expires_at, 'timestamp'):
                                expires_at_aware = expires_at.replace(tzinfo=current_time.tzinfo) if expires_at.tzinfo is None else expires_at
                                current_time_aware = current_time.replace(tzinfo=expires_at.tzinfo) if current_time.tzinfo is None else current_time
                                is_active = current_time_aware < expires_at_aware and ticket_data.get('status', 'valid') == 'valid'
                                ticket_data['expiresAt'] = expires_at.isoformat()
                            else:
                                is_active = ticket_data.get('status', 'valid') == 'valid'
                        except Exception as e:
                            print(f"⚠️ Error checking ticket status: {e}")
                            is_active = ticket_data.get('status', 'valid') == 'valid'
                    else:
                        is_active = ticket_data.get('status', 'valid') == 'valid'
                    
                    # Filter based on requested status
                    if (status == 'active' and is_active) or (status == 'expired' and not is_active):
                        
                        # Get user details
                        user_id = ticket_data.get('userId')
                        if user_id:
                            try:
                                user_ref = db.collection('users').document(user_id)
                                user_doc = user_ref.get()
                                
                                if user_doc.exists:
                                    user_data = user_doc.to_dict()
                                    ticket_data['userName'] = user_data.get('fullName', 'Unknown User')
                                    ticket_data['userEmail'] = user_data.get('email', 'No email')
                                else:
                                    ticket_data['userName'] = 'Unknown User'
                                    ticket_data['userEmail'] = 'No email'
                            except Exception as e:
                                print(f"⚠️ Error getting user details: {e}")
                                ticket_data['userName'] = 'Unknown User'
                                ticket_data['userEmail'] = 'No email'
                        else:
                            ticket_data['userName'] = 'Unknown User'
                            ticket_data['userEmail'] = 'No email'
                        
                        ticket_data['isActive'] = is_active
                        ticket_data['isValid'] = is_active
                        
                        # Handle timestamp
                        if 'timestamp' in ticket_data:
                            timestamp = ticket_data['timestamp']
                            try:
                                if hasattr(timestamp, 'seconds'):
                                    ticket_data['timestamp'] = {'seconds': timestamp.seconds}
                                elif hasattr(timestamp, 'timestamp'):
                                    ticket_data['timestamp'] = {'seconds': int(timestamp.timestamp())}
                            except Exception as e:
                                print(f"⚠️ Error processing timestamp: {e}")
                                ticket_data['timestamp'] = {'seconds': 0}
                        
                        # Ensure required fields
                        ticket_data.setdefault('ticketId', ticket_doc.id)
                        ticket_data.setdefault('vehicleId', 'Unknown')
                        ticket_data.setdefault('farePaid', 0)
                        ticket_data.setdefault('status', 'valid')
                        
                        filtered_tickets.append(ticket_data)
                        
            except Exception as e:
                print(f"⚠️ Error processing ticket by status: {e}")
                continue
        
        print(f"✅ Found {len(filtered_tickets)} {status} tickets for owner")
        
        # Sort by timestamp (newest first)
        try:
            filtered_tickets.sort(key=lambda x: x.get('timestamp', {}).get('seconds', 0), reverse=True)
        except Exception as e:
            print(f"⚠️ Error sorting tickets: {e}")
        
        return jsonify(filtered_tickets)
        
    except Exception as e:
        print(f"❌ Get tickets by status error: {e}")
        return jsonify([])

# --- UPDATE OWNER SETTINGS ---
@app.route("/update-owner-settings", methods=['POST'])
def update_owner_settings():
    if not db: 
        return jsonify({"error": "Database not initialized"}), 500
    
    try:
        data = request.get_json()
        owner_id = data['ownerId']
        
        print(f"🔧 Updating settings for owner: {owner_id}")
        
        updates = {}
        if 'fixedFare' in data:
            updates['fixedFare'] = int(data['fixedFare'])
            print(f"📊 New fare: ₹{data['fixedFare']}")
        if 'ticketValidityMinutes' in data:
            updates['ticketValidityMinutes'] = int(data['ticketValidityMinutes'])
            print(f"⏰ New validity: {data['ticketValidityMinutes']} minutes")
        
        if updates:
            owner_ref = db.collection('owners').document(owner_id)
            owner_doc = owner_ref.get()
            
            if not owner_doc.exists:
                print(f"❌ Owner not found: {owner_id}")
                return jsonify({"error": "Owner not found"}), 404
            
            owner_ref.update(updates)
            print(f"✅ Settings updated successfully")
            
            return jsonify({
                "success": True,
                "message": "Settings updated successfully",
                "updates": updates
            })
        else:
            return jsonify({"error": "No valid fields to update"}), 400
            
    except Exception as e:
        print(f"❌ Update owner settings error: {e}")
        return jsonify({"error": str(e)}), 500

# --- SYNC OWNER EARNINGS ---
@app.route("/sync-owner-earnings/<owner_id>", methods=['POST'])
def sync_owner_earnings(owner_id):
    """Sync owner's totalEarnings with actual ticket revenue"""
    if not db: 
        return jsonify({"error": "Database not initialized"}), 500
    
    try:
        print(f"🔄 Syncing earnings for owner: {owner_id}")
        
        # Calculate actual total from all tickets
        tickets_collection = db.collection('tickets')
        all_tickets = tickets_collection.stream()
        
        total_revenue = 0
        ticket_count = 0
        
        for ticket_doc in all_tickets:
            ticket_data = ticket_doc.to_dict()
            if ticket_data.get('ownerId') == owner_id:
                total_revenue += ticket_data.get('farePaid', 0)
                ticket_count += 1
        
        print(f"💰 Calculated total revenue: ₹{total_revenue} from {ticket_count} tickets")
        
        # Update owner's totalEarnings
        owner_ref = db.collection('owners').document(owner_id)
        owner_ref.update({'totalEarnings': total_revenue})
        
        print(f"✅ Owner earnings synced: ₹{total_revenue}")
        
        return jsonify({
            "success": True,
            "totalRevenue": total_revenue,
            "ticketCount": ticket_count
        })
        
    except Exception as e:
        print(f"❌ Sync earnings error: {e}")
        return jsonify({"error": str(e)}), 500

# --- TICKET VALIDITY CHECK ---
@app.route("/check-ticket-validity/<ticket_id>", methods=['GET'])
def check_ticket_validity(ticket_id):
    """Check if a ticket is still valid"""
    if not db: 
        return jsonify({"error": "Database not initialized"}), 500
    
    try:
        ticket_ref = db.collection('tickets').document(ticket_id)
        ticket_doc = ticket_ref.get()
        
        if not ticket_doc.exists:
            return jsonify({"error": "Ticket not found"}), 404
        
        ticket_data = ticket_doc.to_dict()
        current_time = datetime.now()
        expires_at = ticket_data.get('expiresAt')
        
        if isinstance(expires_at, datetime):
            is_valid = current_time < expires_at and ticket_data.get('status') == 'valid'
        else:
            is_valid = ticket_data.get('status') == 'valid'
        
        # Convert datetime to ISO format for JSON serialization
        expires_at_iso = expires_at.isoformat() if isinstance(expires_at, datetime) else None
        
        return jsonify({
            "ticketId": ticket_id,
            "isValid": is_valid,
            "status": ticket_data.get('status'),
            "expiresAt": expires_at_iso,
            "farePaid": ticket_data.get('farePaid'),
            "vehicleId": ticket_data.get('vehicleId')
        })
        
    except Exception as e:
        print(f"❌ Check ticket validity error: {e}")
        return jsonify({"error": str(e)}), 500

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    app.run(debug=True)
