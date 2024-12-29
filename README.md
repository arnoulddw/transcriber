
```markdown
# Audio Transcriber

This project is an audio transcription application with a user-friendly web interface. It allows you to upload audio files and get transcriptions using either AssemblyAI or OpenAI's Whisper API.

## Features

-   **Web Interface:** A clean and intuitive interface built with HTML, CSS (Materialize CSS), and JavaScript.
-   **Multiple Transcription APIs:** Supports both AssemblyAI and OpenAI Whisper for transcription.
-   **Language Selection:** You can choose the language of the audio or use automatic language detection.
-   **Transcription History:** Stores and displays a history of your transcriptions.
-   **Docker Deployment:** Easy deployment using Docker Compose.
-   **File Cleanup:** Automatically deletes old temporary files to prevent storage issues.

## Prerequisites

-   **API Keys:** You'll need API keys for AssemblyAI and/or OpenAI Whisper. Sign up for accounts on their respective websites to obtain them.
-   **Docker:** Make sure Docker is installed and running on your machine.
-   **Docker Compose:** Docker Compose should also be installed.

## Environment Variables

The application uses the following environment variables:

| Variable                | Description                                                                                             | Accepted Values                                          | Default       |
| :---------------------- | :------------------------------------------------------------------------------------------------------ | :------------------------------------------------------- | :------------ |
| `TZ`                    | The timezone for the application.                                                                      | Any valid timezone string (e.g., `Europe/Amsterdam`, `America/New_York`) | `UTC`         |
| `ASSEMBLYAI_API_KEY`    | Your API key for AssemblyAI.                                                                           | Your AssemblyAI API key                                  | *None (required)* |
| `OPENAI_API_KEY`        | Your API key for OpenAI Whisper.                                                                        | Your OpenAI API key                                     | *None (required)* |
| `DEFAULT_TRANSCRIBE_API` | The default transcription API to use when the application loads.                                      | `assemblyai` or `openai`                                 | `assemblyai`   |
| `DEFAULT_LANGUAGE`      | The default language to use for transcription when the application loads (if applicable to the API). | `auto`, `en`, `nl`, `fr`, `es`                           | `auto`        |

## Installation and Deployment with Docker

### Step 1: Clone the Repository

1. Open a terminal.
2. Navigate to the directory where you want to store the project.
3. Clone this repository (replace with your repository URL):

    ```bash
    git clone [Your-Repository-URL]
    cd [Your-Project-Name]
    ```

### Step 2: Configure Environment Variables in docker-compose.yml

1. Open the  `docker-compose.yml`  file.
2. Add your API keys and other environment variables under the  `environment`  section. Make sure to replace the placeholder values with your actual API keys:

```yaml
services:
  transcriber:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "5001:5001"
    volumes:
      - ./backend:/app/backend
      - ./temp_uploads:/app/temp_uploads
    environment:
      - TZ=${TZ:-UTC}
      - ASSEMBLYAI_API_KEY=your_assemblyai_api_key
      - OPENAI_API_KEY=your_openai_api_key
      - DEFAULT_TRANSCRIBE_API=${DEFAULT_TRANSCRIBE_API:-assemblyai}
      - DEFAULT_LANGUAGE=${DEFAULT_LANGUAGE:-auto}
    restart: unless-stopped
```

### Step 3: Build and Run with Docker Compose

1. In the project's root directory, run the following command:

    ```bash
    docker-compose up -d --build
    ```

    This will build the Docker image and start the container in detached mode.

### Step 4: Access the Application

1. Open your web browser and go to:

    ```
    http://localhost:5001
    ```

## Usage

1. **Upload Audio File:**  Click the "File" button to select an audio file from your computer.
2. **Select API:**  Choose either AssemblyAI or OpenAI Whisper from the dropdown.
3. **Select Language:**  Choose the language of your audio or leave it as "Automatic Detection."
4. **Transcribe:**  Click the "Transcribe" button.
5. **View History:**  Your transcriptions will appear in the "Transcription History" section. You can copy, download, or delete them.

## Development (Local Setup)

If you want to develop or test the application locally before deploying it with Docker, follow these steps:

### Step 1: Set up a Virtual Environment

1. Open your terminal and navigate to the project directory.
2. Create a virtual environment:

    ```bash
    python3 -m venv venv
    ```
3. Activate the virtual environment:

    ```bash
    # On Linux/macOS
    source venv/bin/activate

    # On Windows
    venv\Scripts\activate
    ```

### Step 2: Install Dependencies

1. Install the required Python packages:

    ```bash
    pip install -r backend/requirements.txt
    ```

### Step 3: Configure Environment Variables (Local)

1. You can either set the environment variables temporarily in your terminal:

    ```bash
    # Example for Linux/macOS:
    export ASSEMBLYAI_API_KEY=your_assemblyai_api_key
    export OPENAI_API_KEY=your_openai_api_key
    export TZ=Europe/London
    # ... other variables
    ```

2. Or, you can create a  `.env`  file locally (but don't commit it to Git) and add the variables there. Then, use  `python-dotenv`  to load them in your  `app.py`  (you'll need to install it:  `pip install python-dotenv`).

### Step 4: Run the Application

1. Start the Flask development server:

    ```bash
    python backend/app.py
    ```

2. Access the application in your browser at  `http://127.0.0.1:5001/`.

## Troubleshooting

-   **Port 5001 is in use:**  If port 5001 is already in use, you can change the port mapping in the  `docker-compose.yml`  file.
-   **API Key Errors:**  Double-check that your API keys are correct and that your accounts with AssemblyAI and OpenAI are active.
-   **File Upload Issues:**  Ensure that the file you're uploading is a supported audio format and that it's not too large (especially for OpenAI Whisper, which has a 25MB limit).
-   **Docker Errors:**  If you encounter Docker errors, make sure Docker is running correctly and that you have sufficient permissions.

## Contributing

If you'd like to contribute to this project, please feel free to submit pull requests or open issues on the GitHub repository.

## License

This project is licensed under the MIT License.
```