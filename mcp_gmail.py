import os
from mcp.server.fastmcp import FastMCP # type: ignore
from tools.google import GmailTool

# Determine the working directory of the current script
work_dir = os.path.dirname(__file__)

# Initialize the GmailTool with the path to the client secret file
# It's assumed 'client-secret.json' is in the same directory as this script
gmail_tool = GmailTool(os.path.join(work_dir, 'client-secret.json'))

# Initialize the FastMCP instance for the Gmail application
# Define necessary Python package dependencies for the environment
mcp = FastMCP(
    "Gmail",
    dependencies=[
        "google-api-python-client",   # For interacting with Google APIs
        "google-auth-httplib2",       # HTTP client for Google Auth
        "google-auth-oauthlib",       # OAuth 2.0 library for Google Auth
        "pydantic",                   # Required for EmailMessage and EmailMessages models
        "google-generativeai",        # For Gemini API integration
        "pypdf",                      # For PDF text extraction
        "python-docx",                # For DOCX text extraction
        "python-dotenv",              # For loading environment variables (like GOOGLE_API_KEY)
    ],
)

# Add the GmailTool methods as callable tools to the MCP instance
# Each tool is given a unique name and a descriptive explanation
mcp.add_tool(gmail_tool.send_email, name='Gmail-Send-Email', description='Send an email message in Gmail')
mcp.add_tool(gmail_tool.get_email_message_details, name='Gmail-Get-Email-Message-Details', description='Get details of an email message (Gmail), including attachment summaries.')
mcp.add_tool(gmail_tool.get_email_message_body, name='Get-Email-Message-Body', description='Get the body of an email message (Gmail).')
mcp.add_tool(gmail_tool.search_emails, name='Gmail-Search-Emails', description='Search or return emails in Gmail. Default is None, which returns all email messages.')
mcp.add_tool(gmail_tool.delete_email_message, name='Gmail-Delete-Email-Message', description='Delete an email message in Gmail.')
mcp.add_tool(gmail_tool.download_attachments, name='Gmail-Download-Attachments', description='Download attachments from a Gmail message to a specified local directory.')
