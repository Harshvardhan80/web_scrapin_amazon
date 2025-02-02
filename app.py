from flask import Flask
from dotenv import load_dotenv
import logging
import os
from routes import routes, MongoJSONEncoder  # Import Blueprint and JSON Encoder

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_app():
    app = Flask(__name__)
    
    # Register custom JSON encoder
    app.json_encoder = MongoJSONEncoder
    
    # Register blueprint
    app.register_blueprint(routes)
    
    return app

# ✅ Flask application object ko export karein (Gunicorn isko load karega)
app = create_app()

if __name__ == '__main__':
    app.run(debug=os.getenv('FLASK_ENV', 'development') == 'development')
