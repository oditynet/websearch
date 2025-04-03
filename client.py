from flask import Flask, render_template_string, request
import requests
import webbrowser
from threading import Thread

app = Flask(__name__)
SERVER_URL = "http://localhost:5000"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Поисковик</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
        .search-box { display: flex; gap: 10px; margin-bottom: 20px; }
        input[type="text"] { flex: 1; padding: 10px; font-size: 16px; }
        button { padding: 10px 20px; background: #007bff; color: white; border: none; cursor: pointer; }
        button:hover { background: #0056b3; }
        .results { list-style: none; padding: 0; }
        .result-item { margin-bottom: 15px; padding: 10px; border: 1px solid #ddd; border-radius: 4px; }
        .result-link { font-size: 18px; color: #007bff; text-decoration: none; }
        .snippet { color: #666; margin-top: 5px; }
        .error { color: red; }
        .words-box { margin-top: 20px; max-height: 400px; overflow-y: auto; border: 1px solid #ddd; padding: 10px; border-radius: 4px; }
        .word-item { display: inline-block; margin: 5px; padding: 5px 10px; background: #f0f0f0; border-radius: 15px; cursor: pointer; }
        .word-item:hover { background: #007bff; color: white; }
    </style>
</head>
<body>
    <h1>Поиск по сохраненным страницам</h1>
    <div class="search-box">
        <input type="text" id="query" placeholder="Введите поисковый запрос...">
        <button onclick="performSearch()">Найти</button>
        <button onclick="showAllWords()">Показать все слова</button>
    </div>
    <div id="results"></div>
    <div id="words" class="words-box"></div>

    <script>
        function performSearch() {
            const query = document.getElementById('query').value;
            const resultsDiv = document.getElementById('results');
            resultsDiv.innerHTML = '<div>Идет поиск...</div>';
            
            fetch(`/proxy-search?q=${encodeURIComponent(query)}`)
                .then(response => {
                    if (!response.ok) throw new Error('Ошибка сети');
                    return response.json();
                })
                .then(data => {
                    if (data.error) throw new Error(data.error);
                    
                    const results = data.results || [];
                    if (!Array.isArray(results)) {
                        throw new Error('Некорректный формат ответа');
                    }

                    resultsDiv.innerHTML = results.length === 0 
                        ? '<div>Ничего не найдено</div>'
                        : `<ul class="results">${
                            results.map(result => `
                                <div class="result-item">
                                    <a href="${result.url}" class="result-link" target="_blank">
                                        ${result.domain || result.url}
                                    </a>
                                    <div class="snippet">${result.snippet}</div>
                                </div>
                            `).join('')
                        }</ul>`;
                })
                .catch(error => {
                    resultsDiv.innerHTML = `<div class="error">Ошибка: ${error.message}</div>`;
                });
        }

        function showAllWords() {
            const wordsDiv = document.getElementById('words');
            wordsDiv.innerHTML = '<div>Загрузка слов...</div>';
            
            fetch('/proxy-all-words')
                .then(response => response.json())
                .then(data => {
                    if(data.error) {
                        wordsDiv.innerHTML = `<div class="error">${data.error}</div>`;
                        return;
                    }
                    
                    wordsDiv.innerHTML = `
                        <div>Найдено слов: ${data.count}</div>
                        ${data.words.map(word => 
                            `<div class="word-item" onclick="searchWord('${word}')">${word}</div>`
                        ).join('')}
                    `;
                })
                .catch(error => {
                    wordsDiv.innerHTML = `<div class="error">Ошибка: ${error.message}</div>`;
                });
        }

        function searchWord(word) {
            document.getElementById('query').value = word;
            performSearch();
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/proxy-search')
def proxy_search():
    try:
        response = requests.get(f"{SERVER_URL}/search", params={'q': request.args.get('q', '')}, timeout=5)
        return response.json()
    except requests.exceptions.RequestException as e:
        return {'results': [], 'error': f'Ошибка соединения: {str(e)}'}

@app.route('/proxy-all-words')
def proxy_all_words():
    try:
        response = requests.get(f"{SERVER_URL}/all-words", timeout=10)
        return response.json()
    except requests.exceptions.RequestException as e:
        return {'error': f'Ошибка соединения: {str(e)}'}

def open_browser():
    webbrowser.open_new('http://127.0.0.1:5001')

if __name__ == '__main__':
    Thread(target=open_browser).start()
    app.run(port=5001, use_reloader=False)
