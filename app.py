import os
from flask import Flask, request, jsonify
import google.generativeai as genai
import json
from dotenv import load_dotenv

# Optional: For robust MIME type detection if request.files['image'].mimetype isn't always reliable
# from PIL import Image
# import io

load_dotenv() # Load environment variables from .env file

app = Flask(__name__)

# Configure Google Gemini API key from environment variable
# IMPORTANT: Never hardcode your API key directly in production code.
# Use environment variables or a more secure configuration management.
# For local development with .env, this is fine.
genai.configure(api_key=os.getenv("GEMINI_API_KEY")) # Use os.getenv to safely retrieve from .env


@app.route('/test')
def test():
    return "hello shravan"

@app.route('/process_image', methods=['POST'])
def process_image():
    if 'image' not in request.files:
        return jsonify({'error': 'No image file provided'}), 400

    image_file = request.files['image']
    if image_file.filename == '':
        return jsonify({'error': 'No selected image file'}), 400

    try:
        # Read image data
        image_bytes = image_file.read()

        # Determine MIME type:
        # Most reliable: Use image_file.mimetype directly from the multipart request.
        # This is what you had, and it's generally correct for files uploaded via Flutter's http.MultipartFile.
        mime_type = image_file.mimetype

        # Fallback (uncomment and use instead of image_file.mimetype if you still get octet-stream errors)
        # mime_type = get_image_mime_type(image_bytes)
        # if mime_type == 'application/octet-stream':
        #     # If PIL couldn't determine a proper type, it's likely an unsupported format or corrupted.
        #     return jsonify({'error': 'Unsupported image format or failed to determine MIME type from content'}), 400


        # Use the recommended model
        model = genai.GenerativeModel('gemini-1.5-flash') # Good choice for speed and performance

        # Prepare the image for Gemini (as a part, along with text)
        image_part = {
            'mime_type': mime_type, # Use the determined MIME type
            'data': image_bytes
        }

        # Define the prompt for Gemini
        prompt_text = """
        Analyze this image of a medical prescription.
        For each distinct medicine listed, extract the following information:
        - **name**: The name of the medicine (e.g., "Paracetamol", "Amoxicillin").
        - **quantity**: The dosage or quantity (e.g., "500mg", "1 tablet", "2.5ml"). If not explicitly mentioned, infer from context if possible or leave empty.
        - **duration**: The duration of use in number of days (e.g., "for 7 days", "5 days"). Extract only the number. If not specified, use a default value of -1.
        - **meal**: When to take the medicine relative to meals (e.g., "after meal", "before meal", "with food", "empty stomach"). If not specified, use "anytime".
        - **frequency**: How often to take the medicine (e.g., "twice a day", "daily", "every 8 hours"). If mentioned as (1-0-1), convert it to "twice a day". If not specified, leave empty.

        Return the information as a JSON array of objects.
        Example of expected JSON structure:
        [
            {
                "name": "Medicine A",
                "quantity": "500mg",
                "duration": 7,
                "meal": "after meal",
                "frequency": "twice a day"
            },
            {
                "name": "Medicine B",
                "quantity": "1 tablet",
                "duration": 5,
                "meal": "before meal",
                "frequency": "daily"
            }
        ]
        If no medicine information is found, return an empty array `[]`.
        Do not include any other text or formatting, just the JSON array.
        """

        # Generate content using the Gemini model
        response = model.generate_content([prompt_text, image_part])

        # Extract the text response from Gemini
        gemini_response_text = response.text.strip()
        print(f"Gemini raw response: {gemini_response_text}") # For debugging

        # Attempt to parse the JSON from Gemini's response
        medicine_details = []
        try:
            # Important: Gemini often wraps its JSON in markdown code blocks (```json ... ```)
            # You need to remove these before parsing.
            if gemini_response_text.startswith("```json"):
                gemini_response_text = gemini_response_text.replace("```json", "", 1).strip()
            if gemini_response_text.endswith("```"):
                gemini_response_text = gemini_response_text[:-3].strip()

            # Clean up any potential trailing commas or other malformations if they occur
            # This is a very basic attempt; complex malformations might need a proper JSON linter/fixer
            gemini_response_text = gemini_response_text.replace(",]", "]").replace(",}", "}").strip()


            parsed_json = json.loads(gemini_response_text)
            if isinstance(parsed_json, list):
                medicine_details = parsed_json
            else:
                # If Gemini sometimes returns a single object instead of a list, wrap it
                if isinstance(parsed_json, dict):
                    medicine_details = [parsed_json]
                else:
                    print(f"Gemini returned non-list, non-dict JSON: {parsed_json}")
                    medicine_details = [] # Fallback
        except json.JSONDecodeError as json_e:
            print(f"Error decoding JSON from Gemini: {json_e}")
            print(f"Malformed JSON string that caused error: '{gemini_response_text}'")
            medicine_details = [] # Fallback to empty list on parsing error

        # Further refinement of extracted data for Flutter's MedicineInfo class:
        # Ensure 'duration' is an int and 'meal' is a string.
        # The prompt asks for duration as a number, and 'anytime' for meal.
        # This loop ensures the data types match your Flutter `MedicineInfo` expectations.
        for item in medicine_details:
            # Convert duration to int, default to -1 if not found or invalid
            try:
                item['duration'] = int(item.get('duration', -1))
            except (ValueError, TypeError):
                item['duration'] = -1

            # Ensure meal is a string, default to "anytime" if null/empty from Gemini
            item['meal'] = item.get('meal', 'anytime') or 'anytime' # Handles both missing key and null value

            # Ensure frequency is a string, default to empty if null/missing
            item['frequency'] = item.get('frequency', '') or ''

            # Ensure quantity is a string, default to empty if null/missing
            item['quantity'] = item.get('quantity', '') or ''

            # Ensure name is a string, default to empty if null/missing
            item['name'] = item.get('name', '') or ''


        return jsonify({
            'extracted_text': gemini_response_text, # Still useful for backend debugging
            'medicine_details': medicine_details
        }), 200

    except Exception as e:
        print(f"Server error: {e}")
        # Return a more generic error for the client, log details on server
        return jsonify({'error': 'An internal server error occurred during image processing.'}), 500

if __name__ == '__main__':
    # When running in production, set debug=False
    app.run(debug=True, host='0.0.0.0', port=5000)
