# SarkariGPT - Government Schemes Assistant

An AI-powered assistant designed to help Indian citizens navigate government schemes, tax benefits, and subsidies through multilingual conversations.

## Features

- **Personalized Recommendations**: Based on user profile (state, income, occupation, category)
- **Multilingual Support**: Hindi, English, Bengali, Tamil, Telugu, Marathi, Gujarati
- **Voice Input/Output**: Speech-to-text and text-to-speech capabilities
- **MyScheme.gov.in Integration**: Direct scraping and search from official portal
- **Chat History**: Persistent conversations for contextual assistance
- **Eligibility Filtering**: Shows only schemes user is actually eligible for

## Setup

1. Clone this repository
2. Install dependencies: `pip install -r app_requirements.txt`
3. Get a Groq API key from [console.groq.com](https://console.groq.com)
4. Run: `streamlit run pain.py`

## Usage

1. Enter your Groq API key in the sidebar
2. Fill your personal profile in the "Personal Profile" tab
3. Ask questions about government schemes in the "Chat" tab
4. Get personalized recommendations based on your eligibility

## Deployment

### Streamlit Community Cloud

1. Push code to GitHub repository
2. Visit [share.streamlit.io](https://share.streamlit.io)
3. Deploy from your GitHub repository
4. Add GROQ_API_KEY to secrets in deployment settings

## Tech Stack

- **Frontend**: Streamlit
- **AI**: Groq LLM (Llama 3.1)
- **Web Scraping**: Trafilatura
- **Database**: Simple vector search
- **Translation**: Google Translate
- **Speech**: Google Text-to-Speech, SpeechRecognition

## License

MIT License
