"""
SarkariGPT - AI Assistant for Indian Government Schemes

Requirements.txt (install these packages):
streamlit
groq
beautifulsoup4
speechrecognition
gtts
langdetect
googletrans==3.1.0a0
requests
trafilatura
"""

import streamlit as st
import requests
import trafilatura
from groq import Groq
import speech_recognition as sr
from gtts import gTTS
import tempfile
import os
import json
import time
from typing import List, Dict, Any
from googletrans import Translator, LANGUAGES
from langdetect import detect
import io
import base64
from urllib.parse import urljoin, urlparse
import re
import pickle
from datetime import datetime

# Page configuration
st.set_page_config(
    page_title="SarkariGPT - Government Schemes Assistant",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'schemes_data' not in st.session_state:
    st.session_state.schemes_data = []
if 'last_scrape_time' not in st.session_state:
    st.session_state.last_scrape_time = 0
if 'user_profile' not in st.session_state:
    st.session_state.user_profile = {}
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []

class SimpleVectorDB:
    """Simple in-memory vector database using basic text search"""
    def __init__(self):
        self.documents = []
        self.metadata = []
        self.ids = []
    
    def add(self, documents: List[str], metadatas: List[Dict], ids: List[str]):
        """Add documents to the database"""
        self.documents.extend(documents)
        self.metadata.extend(metadatas)
        self.ids.extend(ids)
    
    def query(self, query_text: str, n_results: int = 5) -> Dict:
        """Simple text-based search"""
        query_lower = query_text.lower()
        scores = []
        
        for i, doc in enumerate(self.documents):
            doc_lower = doc.lower()
            # Simple scoring based on word matches
            score = 0
            words = query_lower.split()
            for word in words:
                if word in doc_lower:
                    score += doc_lower.count(word)
            scores.append((score, i))
        
        # Sort by score and get top results
        scores.sort(reverse=True)
        top_indices = [idx for _, idx in scores[:n_results] if scores[0][0] > 0]
        
        return {
            'documents': [[self.documents[i] for i in top_indices]],
            'metadatas': [[self.metadata[i] for i in top_indices]],
            'distances': [[1.0 / (score + 1) for score, _ in scores[:len(top_indices)]]]
        }

class SarkariGPT:
    def __init__(self, groq_api_key: str):
        self.groq_client = Groq(api_key=groq_api_key) if groq_api_key else None
        self.translator = Translator()
        self.recognizer = sr.Recognizer()
        self.base_url = "https://www.myscheme.gov.in"
        self.setup_vector_db()
        self.load_user_profile()
    
    def load_user_profile(self):
        """Load user profile from disk if exists"""
        try:
            if os.path.exists('user_profile.pkl'):
                with open('user_profile.pkl', 'rb') as f:
                    st.session_state.user_profile = pickle.load(f)
        except Exception as e:
            st.session_state.user_profile = {}
        
        # Load chat history
        try:
            if os.path.exists('chat_history.pkl'):
                with open('chat_history.pkl', 'rb') as f:
                    st.session_state.chat_history = pickle.load(f)
        except Exception as e:
            st.session_state.chat_history = []
    
    def save_user_profile(self, profile_data: Dict):
        """Save user profile to disk and session"""
        try:
            st.session_state.user_profile.update(profile_data)
            with open('user_profile.pkl', 'wb') as f:
                pickle.dump(st.session_state.user_profile, f)
        except Exception as e:
            st.error(f"Error saving profile: {str(e)}")
    
    def setup_vector_db(self):
        """Initialize simple vector database"""
        try:
            # Load existing data if available
            if os.path.exists('schemes_db.pkl'):
                with open('schemes_db.pkl', 'rb') as f:
                    self.vector_db = pickle.load(f)
            else:
                self.vector_db = SimpleVectorDB()
            return True
        except Exception as e:
            st.error(f"Error setting up database: {str(e)}")
            self.vector_db = SimpleVectorDB()
            return False
    
    def get_eligible_schemes(self, user_query: str = "") -> List[Dict]:
        """Get schemes based on user eligibility criteria"""
        profile = st.session_state.user_profile
        
        # Build eligibility search query
        eligibility_terms = []
        
        if profile.get('state'):
            eligibility_terms.append(profile['state'])
        if profile.get('category'):
            eligibility_terms.append(profile['category'])
        if profile.get('occupation'):
            eligibility_terms.append(profile['occupation'])
        if profile.get('income_range'):
            eligibility_terms.append(profile['income_range'])
        if profile.get('age_group'):
            eligibility_terms.append(profile['age_group'])
        if profile.get('gender'):
            eligibility_terms.append(profile['gender'])
        
        # Combine user query with eligibility terms
        search_query = f"{user_query} {' '.join(eligibility_terms)}"
        
        # Search for relevant schemes
        relevant_schemes = self.search_schemes(search_query, n_results=10)
        
        # Filter schemes based on eligibility criteria
        eligible_schemes = []
        for scheme in relevant_schemes:
            content_lower = scheme['content'].lower()
            is_eligible = True
            
            # Check income eligibility
            if profile.get('annual_income'):
                income = profile['annual_income']
                # Simple income-based filtering
                if income > 800000 and ('bpl' in content_lower or 'below poverty line' in content_lower):
                    is_eligible = False
                elif income < 200000 and ('above 8 lakh' in content_lower or 'high income' in content_lower):
                    is_eligible = False
            
            # Check state eligibility
            if profile.get('state') and profile['state'].lower() not in content_lower:
                # If scheme is state-specific and doesn't match user's state, skip
                state_keywords = ['state government', 'state scheme', profile['state'].lower()]
                if any(keyword in content_lower for keyword in state_keywords):
                    if profile['state'].lower() not in content_lower:
                        is_eligible = False
            
            if is_eligible:
                eligible_schemes.append(scheme)
        
        return eligible_schemes[:5]  # Return top 5 eligible schemes
    
    def web_search_schemes(self, query: str) -> List[Dict]:
        """Search for additional scheme information from web if needed"""
        try:
            # Construct search URL for MyScheme portal
            search_url = f"{self.base_url}/find-scheme"
            
            # Try to get additional content
            downloaded = trafilatura.fetch_url(search_url)
            if downloaded:
                text_content = trafilatura.extract(downloaded)
                if text_content:
                    return [{
                        'content': text_content[:2000],
                        'metadata': {
                            'category': 'Web Search Results',
                            'url': search_url,
                            'scraped_at': time.time()
                        }
                    }]
        except Exception as e:
            pass
        
        return []
    
    def scrape_myscheme_data(self) -> List[Dict]:
        """Scrape government schemes from MyScheme portal"""
        schemes_data = []
        
        try:
            # Main categories to scrape
            categories = [
                "agriculture-rural-environment",
                "banking-financial-services-insurance",
                "business-entrepreneurship",
                "education-learning",
                "health-wellness",
                "housing-shelter",
                "skills-employment",
                "social-welfare-empowerment"
            ]
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for i, category in enumerate(categories):
                status_text.text(f"Scraping category: {category}")
                
                try:
                    # Scrape category page
                    category_url = f"{self.base_url}/find-scheme?category={category}"
                    downloaded = trafilatura.fetch_url(category_url)
                    
                    if downloaded:
                        text_content = trafilatura.extract(downloaded)
                        if text_content:
                            schemes_data.append({
                                'category': category.replace('-', ' ').title(),
                                'url': category_url,
                                'content': text_content[:5000],  # Limit content size
                                'scraped_at': time.time()
                            })
                
                except Exception as e:
                    st.warning(f"Error scraping {category}: {str(e)}")
                
                progress_bar.progress((i + 1) / len(categories))
                time.sleep(0.5)  # Rate limiting
            
            progress_bar.empty()
            status_text.empty()
            
            # Store schemes data in vector database
            if schemes_data:
                self.store_in_vector_db(schemes_data)
                st.session_state.schemes_data = schemes_data
                st.session_state.last_scrape_time = time.time()
            
            return schemes_data
            
        except Exception as e:
            st.error(f"Error during scraping: {str(e)}")
            return []
    
    def store_in_vector_db(self, schemes_data: List[Dict]):
        """Store scraped data in vector database"""
        try:
            documents = []
            metadatas = []
            ids = []
            
            for i, scheme in enumerate(schemes_data):
                documents.append(scheme['content'])
                metadatas.append({
                    'category': scheme['category'],
                    'url': scheme['url'],
                    'scraped_at': scheme['scraped_at']
                })
                ids.append(f"scheme_{i}_{int(scheme['scraped_at'])}")
            
            # Add to vector database
            self.vector_db.add(
                documents=documents,
                metadatas=metadatas,
                ids=ids
            )
            
            # Save to disk
            with open('schemes_db.pkl', 'wb') as f:
                pickle.dump(self.vector_db, f)
            
            st.success(f"Successfully stored {len(schemes_data)} schemes in database!")
            
        except Exception as e:
            st.error(f"Error storing data in database: {str(e)}")
    
    def search_schemes(self, query: str, n_results: int = 5) -> List[Dict]:
        """Search for relevant schemes using vector similarity"""
        try:
            if not self.vector_db:
                return []
            
            results = self.vector_db.query(query, n_results=n_results)
            
            search_results = []
            if results['documents'] and results['documents'][0]:
                for i in range(len(results['documents'][0])):
                    search_results.append({
                        'content': results['documents'][0][i],
                        'metadata': results['metadatas'][0][i],
                        'distance': results['distances'][0][i] if results.get('distances') else 0
                    })
            
            return search_results
            
        except Exception as e:
            st.error(f"Error searching schemes: {str(e)}")
            return []
    
    def detect_language(self, text: str) -> str:
        """Detect language of input text"""
        try:
            detected = detect(text)
            return detected if detected in ['hi', 'en', 'bn', 'ta', 'te', 'mr', 'gu', 'kn', 'ml', 'pa'] else 'en'
        except:
            return 'en'
    
    def translate_text(self, text: str, target_lang: str = 'en') -> str:
        """Translate text to target language"""
        try:
            if target_lang == 'en':
                return text
            
            translation = self.translator.translate(text, dest=target_lang)
            result = getattr(translation, 'text', None)
            return str(result) if result else text
        except Exception as e:
            st.warning(f"Translation error: {str(e)}")
            return text
    
    def speech_to_text(self, audio_data) -> str:
        """Convert speech to text"""
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
                tmp_file.write(audio_data.getvalue())
                tmp_file_path = tmp_file.name
            
            with sr.AudioFile(tmp_file_path) as source:
                audio = self.recognizer.record(source)
                # Use getattr to handle potential method availability issues
                recognize_func = getattr(self.recognizer, 'recognize_google', None)
                if recognize_func:
                    text = recognize_func(audio, language='hi-IN')
                else:
                    text = "Speech recognition not available"
            
            os.unlink(tmp_file_path)
            return str(text) if text else ""
            
        except Exception as e:
            st.error(f"Speech recognition error: {str(e)}")
            return ""
    
    def text_to_speech(self, text: str, lang: str = 'hi') -> bytes:
        """Convert text to speech"""
        try:
            tts = gTTS(text=text, lang=lang, slow=False)
            fp = io.BytesIO()
            tts.write_to_fp(fp)
            fp.seek(0)
            return fp.getvalue()
        except Exception as e:
            st.error(f"Text-to-speech error: {str(e)}")
            return b""
    
    def generate_response(self, user_query: str, language: str = 'en') -> str:
        """Generate AI response using Groq API with personalized eligibility"""
        try:
            if not self.groq_client:
                return "Please provide a valid Groq API key in the sidebar."
            
            # Get user profile for personalization
            profile = st.session_state.user_profile
            
            # Get eligible schemes based on user profile
            eligible_schemes = self.get_eligible_schemes(user_query)
            
            # If no eligible schemes found, do web search
            if not eligible_schemes:
                web_results = self.web_search_schemes(user_query)
                eligible_schemes.extend(web_results)
            
            # Build context from eligible schemes
            context = ""
            profile_context = ""
            
            # Add user profile context
            if profile:
                profile_context = "User Profile:\n"
                if profile.get('name'):
                    profile_context += f"Name: {profile['name']}\n"
                if profile.get('state'):
                    profile_context += f"State: {profile['state']}\n"
                if profile.get('category'):
                    profile_context += f"Category: {profile['category']}\n"
                if profile.get('occupation'):
                    profile_context += f"Occupation: {profile['occupation']}\n"
                if profile.get('annual_income'):
                    profile_context += f"Annual Income: ₹{profile['annual_income']:,}\n"
                if profile.get('age_group'):
                    profile_context += f"Age Group: {profile['age_group']}\n"
                if profile.get('gender'):
                    profile_context += f"Gender: {profile['gender']}\n"
                profile_context += "\n"
            
            if eligible_schemes:
                context = "Eligible government schemes for this user:\n\n"
                for i, scheme in enumerate(eligible_schemes, 1):
                    context += f"{i}. Category: {scheme['metadata']['category']}\n"
                    context += f"Content: {scheme['content'][:800]}\n"
                    context += f"Source: {scheme['metadata']['url']}\n\n"
            
            # Create prompt based on language
            if language == 'hi':
                system_prompt = """आप SarkariGPT हैं, भारत सरकार की योजनाओं के विशेषज्ञ हैं। आपका काम है:
1. उपयोगकर्ता की पात्रता जांचना
2. योजना के फायदे बताना
3. आवेदन की प्रक्रिया समझाना
4. सीधा लिंक देना
5. सरल हिंदी में जवाब देना

हमेशा helpful, accurate और friendly रहें। केवल MyScheme.gov.in की जानकारी का उपयोग करें।"""
            else:
                system_prompt = """You are SarkariGPT, an expert on Indian government schemes from MyScheme.gov.in portal. Your role is to:
1. Check user eligibility for schemes based on their profile
2. Explain scheme benefits clearly with exact amounts
3. Provide step-by-step application process
4. Give direct MyScheme.gov.in links when available
5. Focus only on schemes from MyScheme portal

Always be helpful, accurate, and personalized based on user profile."""
            
            # Add chat history context
            chat_context = ""
            if st.session_state.chat_history:
                chat_context = "Previous conversation context:\n"
                for msg in st.session_state.chat_history[-3:]:  # Last 3 exchanges
                    chat_context += f"User: {msg.get('user', '')}\n"
                    chat_context += f"Assistant: {msg.get('assistant', '')[:200]}...\n\n"
            
            # Create user message
            user_message = f"""
{profile_context}
{chat_context}
User Query: {user_query}

Context Information from MyScheme.gov.in:
{context}

Please provide a comprehensive answer about government schemes from MyScheme portal relevant to this query. Focus ONLY on schemes the user is ELIGIBLE for based on their profile. Include:
1. Specific eligibility criteria (check against user profile)
2. Benefits available and potential savings
3. Step-by-step application process
4. Required documents
5. Direct MyScheme.gov.in links if available
6. Deadlines and important dates

Respond in {'Hindi' if language == 'hi' else 'English'}.
"""
            
            # Generate response using Groq
            response = self.groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                max_tokens=1500,
                temperature=0.3
            )
            
            generated_response = response.choices[0].message.content or "No response generated"
            
            # Save complete interaction to chat history
            st.session_state.chat_history.append({
                'user': user_query,
                'assistant': generated_response,
                'timestamp': datetime.now().isoformat()
            })
            
            # Save chat history to disk
            try:
                with open('chat_history.pkl', 'wb') as f:
                    pickle.dump(st.session_state.chat_history[-50:], f)  # Keep last 50 exchanges
            except Exception as e:
                pass  # Silent fail for chat history saving
            
            return generated_response
            
        except Exception as e:
            return f"Error generating response: {str(e)}. Please check your API key and try again."

def main():
    # Title and description
    st.title("🏛️ SarkariGPT - Government Schemes Assistant")
    st.markdown("### Discover and understand Indian government schemes through AI-powered multilingual conversations")
    
    # Create tabs
    tab1, tab2, tab3 = st.tabs(["💬 Chat", "👤 Personal Profile", "📊 Data & Settings"])
    
    # Sidebar for basic configuration only
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        # Groq API Key input - supports both secrets and manual input
        groq_api_key = ""
        try:
            groq_api_key = st.secrets["GROQ_API_KEY"]
            st.success("✅ API key loaded from secrets")
        except:
            groq_api_key = st.text_input(
                "Groq API Key",
                type="password",
                help="Enter your Groq API key to enable AI responses"
            )
        
        # Language selection
        language_options = {
            'English': 'en',
            'हिंदी (Hindi)': 'hi',
            'বাংলা (Bengali)': 'bn',
            'தமிழ் (Tamil)': 'ta',
            'తెలుగు (Telugu)': 'te',
            'मराठी (Marathi)': 'mr',
            'ગુજરાતી (Gujarati)': 'gu'
        }
        
        selected_language = st.selectbox(
            "Select Language / भाषा चुनें",
            list(language_options.keys()),
            index=0
        )
        
        language_code = language_options[selected_language]
        
        st.divider()
        
        # About section
        st.header("ℹ️ About SarkariGPT")
        st.markdown("""
        **SarkariGPT** helps you:
        - 🎯 Find eligible government schemes
        - 💰 Understand benefits and savings
        - 📋 Get step-by-step application guidance
        - 🔗 Access direct government links
        - 🗣️ Communicate in your preferred language
        """)
    
    # Initialize SarkariGPT
    sarkari_gpt = SarkariGPT(groq_api_key)
    
    # Tab 1: Chat Interface
    with tab1:
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.header("💬 Ask About Government Schemes")
            
            # Show profile status
            if st.session_state.user_profile:
                profile = st.session_state.user_profile
                st.info(f"🎯 Personalized for: {profile.get('name', 'User')} | {profile.get('state', 'India')} | {profile.get('occupation', 'Citizen')}")
            else:
                st.warning("Complete your profile in the 'Personal Profile' tab for personalized scheme recommendations.")
            
            # Display chat messages
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])
                    
                    # Add audio playback for assistant messages
                    if message["role"] == "assistant" and message.get("audio_data"):
                        try:
                            audio_bytes = base64.b64decode(message["audio_data"])
                            st.audio(audio_bytes, format='audio/mp3')
                        except Exception as e:
                            pass  # Skip audio if there's an error
            
            # Input methods
            input_method = st.radio(
                "Input Method / इनपुट विधि",
                ["💬 Text", "🎤 Voice"],
                horizontal=True
            )
            
            user_input = ""
            
            if input_method == "💬 Text":
                user_input = st.chat_input("Ask about government schemes... / सरकारी योजनाओं के बारे में पूछें...")
            
            elif input_method == "🎤 Voice":
                st.info("Voice input feature requires microphone access. Please ensure your browser allows microphone access.")
                
                # Audio recording placeholder
                audio_bytes = st.audio_input("Record your question", key="voice_input")
                
                if audio_bytes:
                    with st.spinner("Converting speech to text..."):
                        user_input = sarkari_gpt.speech_to_text(audio_bytes)
                        if user_input:
                            st.success(f"Recognized: {user_input}")
                        else:
                            st.error("Could not recognize speech. Please try again.")
            
            # Process user input
            if user_input:
                # Add user message to chat
                st.session_state.messages.append({"role": "user", "content": user_input})
                
                with st.chat_message("user"):
                    st.markdown(user_input)
                
                # Generate AI response
                with st.chat_message("assistant"):
                    with st.spinner("Generating response..."):
                        if not groq_api_key:
                            response = "Please provide your Groq API key in the sidebar to get AI-powered responses."
                        else:
                            # Detect input language and translate if needed
                            detected_lang = sarkari_gpt.detect_language(user_input)
                            
                            # Translate query to English for better search
                            english_query = user_input
                            if detected_lang != 'en':
                                english_query = sarkari_gpt.translate_text(user_input, 'en')
                            
                            # Generate response
                            response = sarkari_gpt.generate_response(english_query, language_code)
                            
                            # Translate response to user's preferred language if needed
                            if language_code != 'en' and detected_lang == 'en':
                                response = sarkari_gpt.translate_text(response, language_code)
                        
                        st.markdown(response)
                        
                        # Generate audio response only if voice input was used
                        audio_data = None
                        if input_method == "🎤 Voice" and language_code in ['hi', 'en', 'bn', 'ta', 'te', 'mr', 'gu']:
                            with st.spinner("Generating audio response..."):
                                audio_bytes = sarkari_gpt.text_to_speech(response, language_code)
                                if audio_bytes:
                                    audio_data = audio_bytes
                                    st.audio(audio_bytes, format='audio/mp3')
                
                # Add assistant message to chat
                assistant_message = {
                    "role": "assistant", 
                    "content": response
                }
                if audio_data:
                    assistant_message["audio_data"] = base64.b64encode(audio_data).decode()
                
                st.session_state.messages.append(assistant_message)
                
                # Rerun to update chat
                st.rerun()
        
        with col2:
            # Personalized Recommendations
            if st.session_state.user_profile:
                st.header("🎯 Your Eligible Schemes")
                
                profile = st.session_state.user_profile
                
                # Show personalized scheme recommendations
                if st.button("🔍 Find My Eligible Schemes"):
                    with st.spinner("Finding schemes for you..."):
                        eligible_schemes = sarkari_gpt.get_eligible_schemes()
                        
                        if eligible_schemes:
                            st.success(f"Found {len(eligible_schemes)} schemes you may be eligible for!")
                            
                            for i, scheme in enumerate(eligible_schemes, 1):
                                with st.expander(f"Scheme {i}: {scheme['metadata']['category']}"):
                                    st.write("**Content Preview:**")
                                    st.write(scheme['content'][:300] + "...")
                                    st.write(f"**Source:** {scheme['metadata']['url']}")
                                    
                                    # Quick apply button
                                    if st.button(f"Ask about this scheme", key=f"scheme_{i}"):
                                        query = f"Tell me more about {scheme['metadata']['category']} scheme. Am I eligible and how to apply?"
                                        st.session_state.messages.append({"role": "user", "content": query})
                                        st.rerun()
                        else:
                            st.info("No specific schemes found. Try refreshing the schemes data or updating your profile.")
                
                st.divider()
            
            # Quick actions and information
            st.header("🚀 Quick Actions")
            
            # Personalized sample questions
            st.subheader("💡 Sample Questions")
            
            # Generate personalized questions based on user profile
            if st.session_state.user_profile:
                profile = st.session_state.user_profile
                personalized_questions = []
                
                if profile.get('occupation') == 'Student':
                    personalized_questions.extend([
                        "What scholarship schemes are available for me?",
                        "Education loan schemes for students"
                    ])
                elif profile.get('occupation') == 'Farmer':
                    personalized_questions.extend([
                        "Farmer subsidy schemes in my state",
                        "Crop insurance schemes available"
                    ])
                elif profile.get('occupation') in ['Salaried Employee', 'Private Employee']:
                    personalized_questions.extend([
                        "Tax saving schemes for salaried employees",
                        "Provident fund benefits and schemes"
                    ])
                elif profile.get('occupation') == 'Business Owner':
                    personalized_questions.extend([
                        "MSME loan schemes available",
                        "Business startup government schemes"
                    ])
                
                if profile.get('gender') == 'Female':
                    personalized_questions.append("Women empowerment schemes available")
                
                if profile.get('age_group') == '60+':
                    personalized_questions.append("Senior citizen benefits and schemes")
                
                if personalized_questions:
                    st.write("**Based on your profile:**")
                    for question in personalized_questions[:3]:
                        if st.button(question, key=f"personal_{hash(question)}"):
                            st.session_state.messages.append({"role": "user", "content": question})
                            st.rerun()
            
            # General sample questions
            st.write("**General Questions:**")
            general_questions = [
                "How to apply for PM Kisan Yojana?",
                "What is Ayushman Bharat scheme?",
                "Electric vehicle subsidy eligibility?",
                "Housing scheme for middle class?"
            ]
            
            for question in general_questions:
                if st.button(question, key=f"general_{hash(question)}"):
                    st.session_state.messages.append({"role": "user", "content": question})
                    st.rerun()
    
    # Tab 2: Personal Profile
    with tab2:
        st.header("👤 Personal Profile")
        st.markdown("Enter your details below to get personalized government scheme recommendations")
        
        # Load existing profile
        profile = st.session_state.user_profile
        
        with st.form("user_profile_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("Basic Information")
                
                # Basic Information
                name = st.text_input("Full Name", value=profile.get('name', ''))
                
                # State Selection
                indian_states = [
                    'Andhra Pradesh', 'Arunachal Pradesh', 'Assam', 'Bihar', 'Chhattisgarh',
                    'Goa', 'Gujarat', 'Haryana', 'Himachal Pradesh', 'Jharkhand',
                    'Karnataka', 'Kerala', 'Madhya Pradesh', 'Maharashtra', 'Manipur',
                    'Meghalaya', 'Mizoram', 'Nagaland', 'Odisha', 'Punjab',
                    'Rajasthan', 'Sikkim', 'Tamil Nadu', 'Telangana', 'Tripura',
                    'Uttar Pradesh', 'Uttarakhand', 'West Bengal', 'Delhi', 'Jammu and Kashmir',
                    'Ladakh', 'Chandigarh', 'Dadra and Nagar Haveli', 'Daman and Diu',
                    'Lakshadweep', 'Puducherry', 'Andaman and Nicobar Islands'
                ]
                
                state = st.selectbox("State/UT", ['Select State'] + indian_states, 
                                   index=indian_states.index(profile.get('state', '')) + 1 if profile.get('state') in indian_states else 0)
                
                # Category Selection
                categories = ['General', 'SC', 'ST', 'OBC', 'EWS', 'Minority']
                category = st.selectbox("Category", categories, 
                                      index=categories.index(profile.get('category', 'General')) if profile.get('category') in categories else 0)
                
                # Age Group
                age_groups = ['18-25', '26-35', '36-45', '46-60', '60+']
                age_group = st.selectbox("Age Group", age_groups,
                                       index=age_groups.index(profile.get('age_group', '18-25')) if profile.get('age_group') in age_groups else 0)
                
                # Gender
                gender = st.selectbox("Gender", ['Male', 'Female', 'Other'],
                                    index=['Male', 'Female', 'Other'].index(profile.get('gender', 'Male')) if profile.get('gender') in ['Male', 'Female', 'Other'] else 0)
            
            with col2:
                st.subheader("Economic Information")
                
                # Occupation
                occupations = [
                    'Student', 'Salaried Employee', 'Self Employed', 'Business Owner',
                    'Farmer', 'Daily Wage Worker', 'Unemployed', 'Retired',
                    'Government Employee', 'Private Employee', 'Professional'
                ]
                occupation = st.selectbox("Occupation", occupations,
                                        index=occupations.index(profile.get('occupation', 'Student')) if profile.get('occupation') in occupations else 0)
                
                # Annual Income
                annual_income = st.number_input("Annual Income (₹)", min_value=0, max_value=10000000, 
                                              value=profile.get('annual_income', 0), step=10000)
                
                # Income Range (for easier categorization)
                if annual_income <= 100000:
                    income_range = "Below 1 Lakh"
                elif annual_income <= 300000:
                    income_range = "1-3 Lakh"
                elif annual_income <= 600000:
                    income_range = "3-6 Lakh"
                elif annual_income <= 1000000:
                    income_range = "6-10 Lakh"
                else:
                    income_range = "Above 10 Lakh"
                
                # Family Details
                family_size = st.number_input("Family Size", min_value=1, max_value=20, 
                                            value=profile.get('family_size', 4))
                
                # Special Circumstances
                special_circumstances = st.multiselect(
                    "Special Circumstances (if applicable)",
                    ['Disabled Person', 'Widow', 'Senior Citizen', 'Ex-Serviceman', 
                     'Below Poverty Line', 'Landless', 'Minority Community'],
                    default=profile.get('special_circumstances', [])
                )
            
            # Submit Profile
            submitted = st.form_submit_button("💾 Save Profile", use_container_width=True)
            
            if submitted:
                profile_data = {
                    'name': name,
                    'state': state if state != 'Select State' else '',
                    'category': category,
                    'age_group': age_group,
                    'gender': gender,
                    'occupation': occupation,
                    'annual_income': annual_income,
                    'income_range': income_range,
                    'family_size': family_size,
                    'special_circumstances': special_circumstances,
                    'updated_at': datetime.now().isoformat()
                }
                
                sarkari_gpt.save_user_profile(profile_data)
                st.success("✅ Profile saved successfully!")
                st.rerun()
        
        # Display current profile summary
        if st.session_state.user_profile:
            st.divider()
            st.subheader("📋 Current Profile Summary")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                if profile.get('name'):
                    st.metric("Name", profile['name'])
                if profile.get('state'):
                    st.metric("State", profile['state'])
                if profile.get('category'):
                    st.metric("Category", profile['category'])
            
            with col2:
                if profile.get('occupation'):
                    st.metric("Occupation", profile['occupation'])
                if profile.get('age_group'):
                    st.metric("Age Group", profile['age_group'])
                if profile.get('gender'):
                    st.metric("Gender", profile['gender'])
            
            with col3:
                if profile.get('annual_income'):
                    st.metric("Annual Income", f"₹{profile['annual_income']:,}")
                if profile.get('income_range'):
                    st.metric("Income Range", profile['income_range'])
                if profile.get('family_size'):
                    st.metric("Family Size", profile['family_size'])
    
    # Tab 3: Data & Settings
    with tab3:
        st.header("📊 Data Management")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Scheme Database")
            
            # Scraping controls
            last_scrape = st.session_state.get('last_scrape_time', 0)
            if last_scrape > 0:
                time_since_scrape = time.time() - last_scrape
                hours_since = int(time_since_scrape // 3600)
                st.info(f"Last scraped: {hours_since} hours ago")
            
            if st.button("🔄 Refresh Schemes Data", use_container_width=True):
                with st.spinner("Scraping latest government schemes from MyScheme.gov.in..."):
                    schemes_data = sarkari_gpt.scrape_myscheme_data()
                    if schemes_data:
                        st.success(f"Successfully loaded {len(schemes_data)} scheme categories!")
                    else:
                        st.error("Failed to scrape data. Please try again.")
            
            # Show data status
            if st.session_state.schemes_data:
                st.metric("Schemes Categories", len(st.session_state.schemes_data))
                st.metric("Total Conversations", len(st.session_state.messages))
            
            if st.session_state.chat_history:
                st.metric("Chat History", f"{len(st.session_state.chat_history)} interactions")
        
        with col2:
            st.subheader("Settings & Info")
            
            # Useful links
            st.markdown("""
            **Official Government Portals:**
            - [MyScheme Portal](https://www.myscheme.gov.in/)
            - [India.gov.in](https://www.india.gov.in/)
            - [PM India](https://www.pmindia.gov.in/)
            - [Digital India](https://digitalindia.gov.in/)
            - [Income Tax Department](https://www.incometax.gov.in/)
            """)
            
            # Clear data options
            st.divider()
            st.subheader("Data Management")
            
            if st.button("🗑️ Clear Chat History", use_container_width=True):
                st.session_state.messages = []
                st.session_state.chat_history = []
                st.success("Chat history cleared!")
                st.rerun()
            
            if st.button("⚠️ Reset Profile", use_container_width=True):
                st.session_state.user_profile = {}
                if os.path.exists('user_profile.pkl'):
                    os.remove('user_profile.pkl')
                st.success("Profile reset!")
                st.rerun()

if __name__ == "__main__":
    main()