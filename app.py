from flask import Flask
from dotenv import load_dotenv
import logging
import os
from routes import routes, MongoJSONEncoder  # Import both Blueprint and MongoJSONEncoder

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

if __name__ == '__main__':
    app = create_app()
    app.run(debug=os.getenv('FLASK_ENV', 'development') == 'development')