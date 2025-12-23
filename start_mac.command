#!/bin/bash
echo "Strat-O-Matic Card Maker"
echo "========================"

# Get the directory of this script
cd "$(dirname "$0")"

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed."
    echo "Please install Python 3.10 or later from https://www.python.org/"
    exit 1
fi

# Check if dependencies are installed
python3 -c "import flask" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "Installing dependencies..."
    pip3 install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to install dependencies."
        exit 1
    fi
fi

# Start the server
echo "Starting Strat-O-Matic Card Maker..."
python3 app.py &
SERVER_PID=$!

# Wait for server to start
sleep 3

# Open browser
if command -v open &> /dev/null; then
    open http://localhost:5000
elif command -v xdg-open &> /dev/null; then
    xdg-open http://localhost:5000
fi

echo ""
echo "Strat-O-Matic Card Maker is running!"
echo "The application should open in your default browser."
echo ""
echo "Press Ctrl+C to stop the server."
echo ""

# Wait for the server process
wait $SERVER_PID
