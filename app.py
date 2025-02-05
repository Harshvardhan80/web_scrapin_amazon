from flask import Flask
import logging
import os
from routes import routes, MongoJSONEncoder  # Import Blueprint and custom JSON Encoder

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_app():
    """Create and configure the Flask app."""
    app = Flask(__name__)

    # Load environment variables directly using Flask's built-in method
    app.config.from_envvar('FLASK_CONFIG', silent=True)

    # Register custom JSON encoder
    app.json_encoder = MongoJSONEncoder
    
    # Register the Blueprint
    app.register_blueprint(routes)

    return app

app = create_app()

if __name__ == '__main__':
    # Ensure the app binds to the correct port
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 10000)))
