# Functional Tests for Workflow Management

This document outlines the structure and guidelines for the functional test suite for the workflow management features of Transcriber.

## Test Environment Setup

To run the tests, you need to set up a dedicated test environment to avoid impacting the development or production databases.

1.  **Install Dependencies:** Ensure all the dependencies in the `requirements.txt` file are installed.
2.  **Configure Environment:** Set up a separate test database and configure the application to use it when running tests. The test configuration is located in `tests/functional/config/test_config.py`.
3.  **Run Migrations:** The test suite now automatically handles database schema initialization.

## Running the Tests

The recommended way to run the test suite is by using Docker Compose for a containerized environment.

### Using Docker Compose (Recommended)

This method ensures a consistent, isolated environment with all necessary services. The process involves three main steps:

**1. Start the Test Database**

This command starts the dedicated MySQL container for testing. It joins the `transcriber_network` Docker network, so start the main stack (`docker compose up -d`) first.

```bash
docker compose -f tests/docker-compose.test.yml up -d
```

**2. Run the Test Suite**

Use the helper script to install dev dependencies inside the test container and execute `pytest`. This ensures every run has the correct tooling without modifying the production image.

```bash
docker compose run --rm -e PYTHONPATH=/app transcriber ./tests/run_tests.sh
```

**3. Shut Down the Test Database**

Once you are finished with testing, run this command to stop and remove the test database container.

```bash
docker compose -f tests/docker-compose.test.yml down
```

## Test Fixtures

The test suite uses a set of `pytest` fixtures to manage the application context, test client, and database state.

-   `app`: Creates and configures a new Flask app instance for each test session.
-   `client`: Provides a test client for the app.
-   `clean_db`: A function-scoped fixture that truncates all tables in the test database before each test. This ensures that tests run in isolation.
-   `logged_in_client`: A function-scoped fixture that provides a logged-in test client with a clean database.

## Test Data

The test suite uses a combination of static fixtures and dynamically generated data to ensure comprehensive coverage. Test data is located in the `tests/functional/helpers/test_data.py` file.

## Troubleshooting

-   **Test Failures:** If a test fails, check the logs for detailed error messages.
-   **Database Issues:** Ensure the test database is properly configured and running. The `clean_db` fixture should handle most database state issues.
-   **`pytest: command not found`:** If you encounter this error, it likely means the Docker image is stale. Rebuild it with `docker compose build --no-cache transcriber` to ensure all dependencies are installed correctly.

## Adding New Tests

When adding new tests, follow these guidelines:

1.  Create a new test file in the appropriate directory (e.g., `tests/functional/workflow/test_new_feature.py`).
2.  Import the necessary helpers and fixtures.
3.  Use the `logged_in_client` fixture to get a test client with a clean database and a logged-in user.
4.  Write clear and concise test cases that cover both success and failure scenarios.
