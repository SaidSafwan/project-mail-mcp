import os
import io
import base64
from typing import Literal, Optional, List, Dict, Any
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pydantic import BaseModel, Field 
from .google_apis import create_service # Assuming google_apis.py is in the same directory or accessible

# Import necessary libraries for file processing and Gemini
from pypdf import PdfReader # For PDF text extraction
from docx import Document # For DOCX text extraction
import google.generativeai as genai
from os import getenv
from dotenv import load_dotenv

# Load environment variables (for GOOGLE_API_KEY)
load_dotenv()

# Gemini API configuration
# It's better to configure it once in the __init__ of the tool
# and get the API key from environment variables for security.
GEMINI_MODEL = "models/gemini-1.5-pro" # Or "gemini-pro" if you prefer

class EmailMessage(BaseModel):
    msg_id: str = Field(..., description="The ID of the email message.")
    subject: str = Field(..., description="The subject of the email message.")
    sender: str = Field(..., description="The sender of the email message.")
    recipients: str = Field(..., description="The recipients of the email message.")
    body: str = Field(..., description="The body of the email message. Note: get_email_message_details sets this to '<not included>'; use get_email_message_body for full content.")
    snippet: str = Field(..., description="A snippet of the email message.")
    has_attachments: bool = Field(..., description="Indicates if the email has attachments.")
    date: str = Field(..., description="The date when the email was sent.")
    star: bool = Field(..., description="Indicates if the email is starred.")
    label: str = Field(..., description="Labels associated with the email message.")
    attachments_info: Optional[List[Dict[str, Any]]] = Field(None, description="Information about email attachments, including content summaries.")


class EmailMessages(BaseModel):
    count: int = Field(..., description="The number of email messages.")
    messages: list[EmailMessage] = Field(..., description="List of email messages.")
    next_page_token: str | None = Field(None, description="Token for the next page of results.")


class GmailTool:
    API_NAME = 'gmail'
    API_VERSION = 'v1'
    SCOPES = ['https://mail.google.com/']

    def __init__(self, client_secret_file: str) -> None:
        self.client_secret_file = client_secret_file
        self._init_service()
        
        # Initialize Gemini model
        api_key = getenv("GOOGLE_API_KEY")
        if not api_key:
            raise Exception("GOOGLE_API_KEY environment variable not set. Please set it.")
        genai.configure(api_key=api_key)
        self.gemini_model = genai.GenerativeModel(GEMINI_MODEL)

    def _init_service(self) -> None:
        """
        Initialize the Gmail API service.
        """
        self.service = create_service(
            self.client_secret_file,
            self.API_NAME,
            self.API_VERSION,
            self.SCOPES
        )

    def _sanitize_filename_part(self, name_part: str, max_length: int = 50) -> str:
        """Sanitizes a string part for use in a filename."""
        if not name_part:
            return "unknown"
        # Remove characters that are problematic for filenames
        invalid_chars = '\\/*?:"<>|'
        for char in invalid_chars:
            name_part = name_part.replace(char, "_")
        name_part = name_part.replace(" ", "_")
        # Limit length of each part
        return name_part[:max_length].strip('_')

    def download_attachments(self, msg_id: str) -> List[str]:
        """
        Downloads attachments from a specific email to an 'Attached_files' folder
        in the specified project directory. Filenames will include sanitized
        subject and sender information.

        Args:
            msg_id (str): The ID of the email message.

        Returns:
            List[str]: A list of file paths for the downloaded attachments.
        """
        message = self.service.users().messages().get(userId='me', id=msg_id).execute()
        payload = message.get('payload', {})
        headers = payload.get('headers', [])
        
        subject = "NoSubject"
        sender_name = "NoSender"

        for header in headers:
            name = header.get('name', '').lower()
            if name == 'subject':
                subject = header.get('value', 'NoSubject')
            elif name == 'from':
                sender_name = header.get('value', 'NoSender')

        sanitized_subject = self._sanitize_filename_part(subject)
        sanitized_sender = self._sanitize_filename_part(sender_name)

        parts = payload.get('parts', [])
        saved_files = []
        
        # Define the save location explicitly to the desired project path
        # Using a raw string (r"...") to handle backslashes in the path
        base_project_path = r"D:\project-mail-mcp-2" # IMPORTANT: Adjust this path as needed
        save_directory_name = "Attached_files"
        save_location = os.path.join(base_project_path, save_directory_name)

        if not os.path.exists(save_location):
            os.makedirs(save_location)
            print(f"Created directory for attachments: {os.path.abspath(save_location)}")

        print(f"Downloading attachments to: {os.path.abspath(save_location)}")

        for part in parts:
            filename = part.get('filename')
            body = part.get('body', {})
            attachment_id = body.get('attachmentId')

            if filename and attachment_id:
                try:
                    attachment = self.service.users().messages().attachments().get(
                        userId='me', messageId=msg_id, id=attachment_id).execute()

                    file_data = base64.urlsafe_b64decode(attachment['data'])
                    
                    sanitized_original_filename = self._sanitize_filename_part(filename, max_length=100)
                    
                    # Construct meaningful filename using sender name
                    new_filename = f"{sanitized_subject}_{sanitized_sender}_{sanitized_original_filename}"
                    # Further sanitize the combined filename to avoid excessive length or problematic chars
                    new_filename = self._sanitize_filename_part(new_filename, max_length=200) 

                    file_path = os.path.join(save_location, new_filename)

                    with open(file_path, 'wb') as f:
                        f.write(file_data)
                    saved_files.append(os.path.abspath(file_path))
                    print(f"Attachment downloaded: {os.path.abspath(file_path)}")
                except Exception as e:
                    print(f"Error downloading attachment {filename}: {e}")

        if not saved_files:
            print("No attachments found or downloaded for this message.")

        return saved_files

    def send_email(
            self,
            to: str,
            subject: str,
            body: str,
            body_type: Literal['plain', 'html'] = 'plain',
            attachment_paths: Optional[List[str]] = None 
    ) -> dict:
        """
        Send an email using the Gmail API.

        Args:
            to (str): Recipient email address.
            subject (str): Email subject.
            body (str): Email body content.
            body_type (str): Type of the body content ('plain' or 'html').
            attachment_paths (list[str]): List of file paths for attachments.

        Returns:
            dict: Response from the Gmail API, including msg_id or error.
        """
        try:
            message = MIMEMultipart()
            message['to'] = to
            message['subject'] = subject

            if body_type.lower() not in ['plain', 'html']:
                return {'error': 'body_type must be either "plain" or "html".', 'status': 'failed'}

            message.attach(MIMEText(body, body_type.lower()))

            if attachment_paths:
                for attachment_path in attachment_paths:
                    if os.path.exists(attachment_path):
                        filename = os.path.basename(attachment_path)
                        with open(attachment_path, "rb") as attachment_file: 
                            part = MIMEBase("application", "octet-stream")
                            part.set_payload(attachment_file.read())
                            encoders.encode_base64(part)
                            part.add_header(
                                "Content-Disposition",
                                f"attachment; filename={filename}",
                            )
                            message.attach(part)
                    else:
                        return {'error': f'File not found - {attachment_path}', 'status': 'failed'}
            
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')

            response = self.service.users().messages().send(
                userId='me',
                body={'raw': raw_message}
            ).execute()

            return {'msg_id': response['id'], 'status': 'success'}

        except Exception as e:
            return {'error': str(e), 'status': 'failed'}

    def search_emails(
            self,
            query: Optional[str] = None,
            label: Literal['ALL', 'INBOX', 'SENT', 'DRAFT', 'SPAM', 'TRASH', 'STARRED', 'UNREAD'] = 'INBOX', 
            max_results: Optional[int] = 10,
            next_page_token: Optional[str] = None
    ) -> EmailMessages: 
        """
        Search for emails in the user's mailbox using the Gmail API.

        Args:
            query (str): Search query string. Default is None.
            label (str): Label to filter the search results. Default is 'INBOX'.
                         Available labels include: 'ALL', 'INBOX', 'SENT', 'DRAFT', 'SPAM', 'TRASH', 'STARRED', 'UNREAD'.
            max_results (int): Maximum number of messages to return. Max allowed by API per page is 500.
            next_page_token (str): Token for fetching the next page of results.

        Returns:
            EmailMessages: An object containing the list of found email messages and a next page token.
        """
        messages_data = [] 
        
        label_ids = []
        if label != 'ALL':
            label_ids = [label.upper()] 

        try:
            result = self.service.users().messages().list(
                userId='me',
                q=query,
                labelIds=label_ids if label_ids else None, 
                maxResults=max_results if max_results is not None else 10, 
                pageToken=next_page_token
            ).execute()

            messages_data.extend(result.get('messages', []))
            current_next_page_token = result.get('nextPageToken')
            
        except Exception as e:
            print(f"Error searching emails: {e}")
            return EmailMessages(count=0, messages=[], next_page_token=None)

        email_messages_list = []
        for message_info in messages_data: 
            msg_id = message_info['id']
            try:
                msg_details = self.get_email_message_details(msg_id)
                email_messages_list.append(msg_details)
            except Exception as e:
                print(f"Error fetching details for message ID {msg_id}: {e}")
        
        return EmailMessages(
            count=len(email_messages_list),
            messages=email_messages_list,
            next_page_token=current_next_page_token 
        )

    def get_email_message_details(
            self,
            msg_id: str
    ) -> EmailMessage:
        """
        Get detailed information about an email message, including attachment summaries.

        Args:
            msg_id (str): The ID of the email message.

        Returns:
            EmailMessage: An object containing details of the email message.
        """
        try:
            message = self.service.users().messages().get(userId='me', id=msg_id, format='full').execute()
            
            payload = message.get('payload', {})
            headers = payload.get('headers', [])

            subject = next((header['value'] for header in headers if header['name'].lower() == 'subject'), 'No Subject')
            sender = next((header['value'] for header in headers if header['name'].lower() == 'from'), 'No Sender')
            recipients = next((header['value'] for header in headers if header['name'].lower() == 'to'), 'No Recipients')
            date = next((header['value'] for header in headers if header['name'].lower() == 'date'), 'No Date')
            
            snippet = message.get('snippet', 'No snippet')
            
            has_attachments = False
            attachments_info = []

            if 'parts' in payload:
                for part in payload['parts']:
                    filename = part.get('filename')
                    body_data = part.get('body', {})
                    attachment_id = body_data.get('attachmentId')
                    mime_type = part.get('mimeType')

                    if filename and attachment_id:
                        has_attachments = True
                        attachment_detail = {
                            'filename': filename,
                            'mime_type': mime_type,
                            'size': body_data.get('size', 0)
                        }
                        
                        try:
                            # Fetch attachment data
                            attachment_response = self.service.users().messages().attachments().get(
                                userId='me', messageId=msg_id, id=attachment_id).execute()
                            file_data_bytes = base64.urlsafe_b64decode(attachment_response['data'])

                            # Extract text and summarize
                            extracted_text = self._extract_text_from_attachment_bytes(file_data_bytes, mime_type)
                            summary = self._summarize_content_with_gemini(extracted_text)
                            attachment_detail['content_summary'] = summary
                        except Exception as attachment_e:
                            attachment_detail['content_summary'] = f"Error processing attachment: {attachment_e}"
                            print(f"Error processing attachment {filename}: {attachment_e}")
                        
                        attachments_info.append(attachment_detail)
            
            label_ids = message.get('labelIds', [])
            star = 'STARRED' in label_ids
            label_str = ', '.join(label_ids) if label_ids else 'No Labels'

            return EmailMessage(
                msg_id=msg_id,
                subject=subject,
                sender=sender,
                recipients=recipients,
                body='<not included>', 
                snippet=snippet,
                has_attachments=has_attachments,
                date=date,
                star=star,
                label=label_str,
                attachments_info=attachments_info
            )
        except Exception as e:
            print(f"Error in get_email_message_details for {msg_id}: {e}")
            return EmailMessage(
                msg_id=msg_id, subject="Error fetching details", sender="", recipients="",
                body="", snippet=str(e), has_attachments=False, date="", star=False, label="ERROR",
                attachments_info=[]
            )

    def _extract_text_from_attachment_bytes(self, content_bytes: bytes, mime_type: str) -> str:
        """
        Extracts text from various file types given their bytes content.
        """
        text_content = ""
        try:
            if mime_type == 'text/plain':
                text_content = content_bytes.decode('utf-8', errors='replace')
            elif mime_type == 'application/pdf':
                with io.BytesIO(content_bytes) as f:
                    reader = PdfReader(f)
                    if reader.pages: # Check if there are any pages
                        text_content = reader.pages[0].extract_text() or "" # Extract only the first page
            elif mime_type == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document': # DOCX
                with io.BytesIO(content_bytes) as f:
                    doc = Document(f)
                    for paragraph in doc.paragraphs:
                        text_content += paragraph.text + "\n"
            elif mime_type.startswith('image/'):
                # For images, if you want actual OCR or image understanding,
                # you'd need to use a dedicated OCR library (like Tesseract with PIL)
                # or pass the image bytes to gemini-pro-vision.
                # For now, we'll return a placeholder.
                return "Image file content cannot be directly extracted as text for summarization."
            else:
                return f"Unsupported attachment type for text extraction: {mime_type}"
        except Exception as e:
            return f"Error extracting text from attachment (type: {mime_type}): {e}"
        
        return text_content if text_content else "No extractable text content found."

    def _summarize_content_with_gemini(self, text_content: str) -> str:
        """
        Summarizes the given text content using the Gemini model.
        """
        if not text_content or text_content.strip() == "No extractable text content found.":
            return "No text content available for summarization."
        
        # Limit the prompt length for the model
        # gemini-1.5-pro has a very large context window, but it's still good practice
        # to manage input size, especially if intermediate steps produce huge text.
        prompt_limit = 1000 # Adjust based on your needs and model's context window
        
        # Construct the summarization prompt
        # prompt = f"Please summarize the following text from a document or email attachment. Focus on key information, main points, and any important numbers or dates. Keep the summary concise and informative.\n\nText:\n{text_content[:prompt_limit]}"
        prompt = text_content[:prompt_limit]

        try:
            # Count tokens (optional, for logging/debugging)
            num_tokens_response = self.gemini_model.count_tokens(prompt)
            num_tokens = num_tokens_response.total_tokens
            print(f"Gemini summarization prompt has {num_tokens} tokens.")

            response = self.gemini_model.generate_content(prompt, stream=False)
            return response.text
        except Exception as e:
            return f"Error summarizing content with Gemini: {e}"


    def get_email_message_body(
            self,
            msg_id: str
    ) -> str:
        """
        Get the text body of an email message using its ID.

        Args:
            msg_id (str): The ID of the email message.

        Returns:
            str: The text body of the email message, or an error message.
        """
        try:
            message = self.service.users().messages().get(userId='me', id=msg_id, format='full').execute()
            payload = message['payload']
            return self._extract_body(payload)
        except Exception as e:
            return f"Error fetching email body for {msg_id}: {str(e)}"

    def _extract_body(
            self,
            payload: dict
    ) -> str:
        """
        Extract the email text body from the payload.
        Prefers 'text/plain' over 'text/html'.

        Args:
            payload (dict): The payload of the email message.

        Returns:
            str: The extracted email body or a placeholder if not found.
        """
        body_content = '<Text body not available>'
        if 'parts' in payload:
            # First pass for text/plain in multipart/alternative
            for part in payload['parts']:
                if part.get('mimeType') == 'multipart/alternative':
                    for subpart in part.get('parts', []):
                        if subpart.get('mimeType') == 'text/plain' and 'data' in subpart.get('body', {}):
                            try:
                                return base64.urlsafe_b64decode(subpart['body']['data']).decode('utf-8', errors='replace')
                            except Exception:
                                pass # Continue to see if other parts work
                # Second pass for direct text/plain parts
                elif part.get('mimeType') == 'text/plain' and 'data' in part.get('body', {}):
                    try:
                        return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='replace')
                    except Exception:
                        pass
            # Fallback if no text/plain found, could try text/html (not implemented here to keep it simple)
        elif 'body' in payload and 'data' in payload['body']: # Single part message
            if payload.get('mimeType') == 'text/plain':
                    try:
                        return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='replace')
                    except Exception:
                        pass
        return body_content


    def delete_email_message(
            self,
            msg_id: str
    ) -> dict:
        """
        Delete an email message using its ID (moves to Trash).

        Args:
            msg_id (str): The ID of the email message.

        Returns:
            dict: {'status': 'success'} or {'error': ..., 'status': 'failed'}
        """
        try:
            self.service.users().messages().delete(userId='me', id=msg_id).execute()
            return {'status': 'success', 'msg_id': msg_id}
        except Exception as e:
            return {'error': f'An error occurred: {str(e)}', 'status': 'failed', 'msg_id': msg_id}

