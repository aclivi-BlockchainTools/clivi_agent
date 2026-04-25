"""
title: Web Search
description: Cerca informació actualitzada a Internet via DuckDuckGo. Útil per a preguntes sobre actualitat, fets recents, documentació tècnica que el model no coneix.
author: tu
version: 1.0.0
license: MIT
requirements: requests, beautifulsoup4
"""

# =============================================================================
# Tool per OpenWebUI — Web Search (DuckDuckGo HTML scraping)
# =============================================================================
# Instal·lació:
#   1. Al servidor on corre OpenWebUI:  pip install requests beautifulsoup4
#   2. A OpenWebUI: Workspace → Tools → "+" → enganxa aquest fitxer.
#   3. Activa la Tool al xat.
#
# Ús típic:
#   "Quan va sortir Python 3.13?"
#   "Busca'm com es configura nginx amb SSL"
#   "Qui va guanyar el Barça-Madrid d'ahir?"
# =============================================================================

from typing import List
import requests
from urllib.parse import quote_plus


class Tools:
    def __init__(self):
        self.citation = True

    def cerca_web(self, consulta: str, num_resultats: int = 5) -> str:
        """
        Cerca informació actualitzada a Internet. Retorna els primers resultats amb títol, URL i resum.
        Utilitza aquesta funció per respondre preguntes sobre esdeveniments recents, informació que pot haver canviat, o temes que no són del teu coneixement intern.

        :param consulta: Pregunta o termes a cercar (llenguatge natural està bé)
        :param num_resultats: Nombre de resultats a retornar (per defecte 5, màxim 10)
        :return: Llistat formatat de resultats amb títol, URL i resum
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return "❌ Falta beautifulsoup4. Instal·la: pip install beautifulsoup4"

        num = max(1, min(int(num_resultats), 10))
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(consulta)}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            )
        }
        try:
            r = requests.post(url, headers=headers, data={"q": consulta}, timeout=15)
            r.raise_for_status()
        except Exception as e:
            return f"❌ Error fent la petició: {e}"

        soup = BeautifulSoup(r.text, "html.parser")
        results: List[str] = []
        for i, result in enumerate(soup.select(".result")):
            if i >= num:
                break
            title_el = result.select_one(".result__title")
            snippet_el = result.select_one(".result__snippet")
            url_el = result.select_one(".result__url")
            if not title_el:
                continue
            title = title_el.get_text(" ", strip=True)
            snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
            result_url = url_el.get_text(" ", strip=True) if url_el else ""
            results.append(f"### {i+1}. {title}\n**URL:** {result_url}\n\n{snippet}\n")

        if not results:
            return f"⚠️ Cap resultat per: '{consulta}'. Prova una altra cerca."
        return f"🔍 Resultats per **'{consulta}'**:\n\n" + "\n---\n\n".join(results)

    def fetch_pagina(self, url: str, max_chars: int = 5000) -> str:
        """
        Descarrega una pàgina web i retorna el seu contingut de text net (sense HTML). Útil quan vols llegir un article sencer d'un resultat de cerca_web.

        :param url: URL completa de la pàgina (http:// o https://)
        :param max_chars: Longitud màxima del text retornat (per defecte 5000)
        :return: Text net extret de la pàgina
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return "❌ Falta beautifulsoup4. Instal·la: pip install beautifulsoup4"
        if not url.startswith(("http://", "https://")):
            return "❌ La URL ha de començar amb http:// o https://"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; OpenWebUI-Tool/1.0)"}
        try:
            r = requests.get(url, headers=headers, timeout=20)
            r.raise_for_status()
        except Exception as e:
            return f"❌ Error descarregant {url}: {e}"
        soup = BeautifulSoup(r.text, "html.parser")
        # Treu elements no desitjats
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
        # Col·lapsa múltiples línies buides
        lines = [l for l in text.splitlines() if l.strip()]
        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n... [truncat] ..."
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else "(sense títol)"
        return f"# {title}\n\n**URL:** {url}\n\n{text}"
