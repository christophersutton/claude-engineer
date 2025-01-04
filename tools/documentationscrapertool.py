from tools.base import BaseTool
import requests
import os
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from tools.webscrapertool import WebScraperTool
from tools.filecreatortool import FileCreatorTool
from tools.createfolderstool import CreateFoldersTool

class DocumentationScraperTool(BaseTool):
    name = "documentationscrapertool"
    description = '''
    Scrapes documentation websites and converts them to structured Markdown files.
    Preserves hierarchy, formatting and technical content while creating a browsable
    local documentation copy with proper internal linking.
    '''
    input_schema = {
        "type": "object",
        "properties": {
            "base_url": {
                "type": "string",
                "description": "Main documentation URL to start scraping from"
            },
            "output_dir": {
                "type": "string", 
                "description": "Directory to save documentation files"
            },
            "rate_limit": {
                "type": "number",
                "description": "Delay between requests in seconds",
                "default": 1.0
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum depth to traverse in doc hierarchy",
                "default": 5
            }
        },
        "required": ["base_url", "output_dir"]
    }

    def __init__(self):
        self.scraper = WebScraperTool()
        self.file_creator = FileCreatorTool()
        self.folder_creator = CreateFoldersTool()
        self.processed_urls = set()
        self.toc_entries = []

    def clean_filename(self, url):
        parsed = urlparse(url)
        filename = parsed.path.strip('/').replace('/', '_')
        if not filename:
            filename = 'index'
        return f"{filename}.md"

    def process_content(self, html_content):
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Remove navigation elements
        for nav in soup.find_all(['nav', 'header', 'footer']):
            nav.decompose()
            
        # Process code blocks
        for pre in soup.find_all('pre'):
            language = pre.get('class', [''])[0] if pre.get('class') else ''
            pre.string = f"```{language}\n{pre.get_text()}\n```"
            
        # Process tables
        for table in soup.find_all('table'):
            # Convert to markdown table format
            markdown_table = self.convert_table_to_markdown(table)
            table.string = markdown_table
            
        return soup.get_text()

    def convert_table_to_markdown(self, table):
        markdown = []
        rows = table.find_all('tr')
        
        # Headers
        headers = rows[0].find_all(['th', 'td'])
        header_row = '| ' + ' | '.join(h.get_text().strip() for h in headers) + ' |'
        markdown.append(header_row)
        
        # Separator
        separator = '|' + '|'.join(['---' for _ in headers]) + '|'
        markdown.append(separator)
        
        # Data rows
        for row in rows[1:]:
            cols = row.find_all('td')
            data_row = '| ' + ' | '.join(c.get_text().strip() for c in cols) + ' |'
            markdown.append(data_row)
            
        return '\n'.join(markdown)

    def extract_links(self, html_content, base_url):
        soup = BeautifulSoup(html_content, 'html.parser')
        links = set()
        
        # Find links in navigation elements and main content
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('#'):
                continue
                
            full_url = urljoin(base_url, href)
            if urlparse(full_url).netloc == urlparse(base_url).netloc:
                links.add(full_url)
                
        return links

    def scrape_page(self, url, current_depth, max_depth):
        if current_depth > max_depth or url in self.processed_urls:
            return
            
        self.processed_urls.add(url)
        
        # Get page content
        response = self.scraper.execute(url=url)
        if not response:
            return
            
        # Process content
        clean_content = self.process_content(response)
        
        # Create file path
        rel_path = urlparse(url).path.strip('/')
        if not rel_path:
            rel_path = 'index'
            
        file_path = os.path.join(self.output_dir, f"{rel_path}.md")
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        # Save content
        self.file_creator.execute(
            content=clean_content,
            filepath=file_path
        )
        
        # Add to TOC
        self.toc_entries.append({
            'depth': current_depth,
            'title': rel_path.split('/')[-1].replace('-', ' ').title(),
            'path': rel_path + '.md'
        })
        
        # Extract and process links
        links = self.extract_links(response, url)
        for link in links:
            time.sleep(self.rate_limit)
            self.scrape_page(link, current_depth + 1, max_depth)

    def generate_toc(self):
        toc_content = "# Documentation Contents\n\n"
        
        for entry in sorted(self.toc_entries, key=lambda x: x['path']):
            indent = '  ' * (entry['depth'] - 1)
            toc_content += f"{indent}* [{entry['title']}]({entry['path']})\n"
            
        toc_path = os.path.join(self.output_dir, 'TOC.md')
        self.file_creator.execute(
            content=toc_content,
            filepath=toc_path
        )

    def execute(self, **kwargs) -> str:
        self.base_url = kwargs['base_url']
        self.output_dir = kwargs['output_dir']
        self.rate_limit = kwargs.get('rate_limit', 1.0)
        max_depth = kwargs.get('max_depth', 5)
        
        # Create output directory
        self.folder_creator.execute(folder_path=self.output_dir)
        
        # Start scraping from base URL
        self.scrape_page(self.base_url, 1, max_depth)
        
        # Generate table of contents
        self.generate_toc()
        
        summary = f"""
        Documentation scraping completed:
        - Processed {len(self.processed_urls)} pages
        - Created {len(self.toc_entries)} markdown files
        - Output directory: {self.output_dir}
        - Table of contents: {os.path.join(self.output_dir, 'TOC.md')}
        """
        
        return summary
