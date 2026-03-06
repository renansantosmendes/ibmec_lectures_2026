"""
Módulo de coleta e extração de notícias do Google News.

Este módulo implementa uma solução orientada a objetos para buscar,
decodificar e extrair o conteúdo de notícias via Google News, seguindo
os princípios SOLID de design de software.
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Protocol, Optional

from pygooglenews import GoogleNews
from googlenewsdecoder import new_decoderv1
from newspaper import Article


# ---------------------------------------------------------------------------
# Configuração de logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Transfer Objects (DTOs)
# ---------------------------------------------------------------------------

@dataclass
class NewsEntry:
    """Representa uma entrada bruta retornada pelo feed do Google News."""

    title: str
    link: str


@dataclass
class NewsArticle:
    """Representa um artigo com URL real e conteúdo já extraído."""

    title: str
    real_url: str
    text: str
    preview: str = field(init=False)

    def __post_init__(self) -> None:
        self.preview = self.text[:300] + "..." if len(self.text) > 300 else self.text


# ---------------------------------------------------------------------------
# Interfaces / Protocolos  (Interface Segregation + Dependency Inversion)
# ---------------------------------------------------------------------------

class NewsFetcher(Protocol):
    """Interface para busca de notícias em qualquer fonte."""

    def fetch(self, query: str, when: str) -> list[NewsEntry]:
        """Busca notícias e retorna uma lista de entradas brutas."""
        ...


class UrlDecoder(Protocol):
    """Interface para decodificação de URLs redirecionadas."""

    def decode(self, url: str) -> Optional[str]:
        """Recebe uma URL encurtada/redirecionada e retorna a URL real, ou None em caso de falha."""
        ...


class ArticleExtractor(Protocol):
    """Interface para extração de conteúdo de um artigo a partir de sua URL."""

    def extract(self, url: str) -> str:
        """Baixa e analisa o artigo, retornando o texto extraído."""
        ...


# ---------------------------------------------------------------------------
# Implementações concretas  (Single Responsibility)
# ---------------------------------------------------------------------------

class GoogleNewsFetcher:
    """
    Implementação de :class:`NewsFetcher` usando a biblioteca ``pygooglenews``.

    Cada instância mantém seu próprio cliente GoogleNews configurado com
    idioma e país definidos na criação.

    Args:
        lang: Código de idioma ISO 639-1 (padrão: ``'pt'``).
        country: Código de país ISO 3166-1 alpha-2 (padrão: ``'BR'``).
    """

    def __init__(self, lang: str = "pt", country: str = "BR") -> None:
        self._client = GoogleNews(lang=lang, country=country)
        self._logger = logging.getLogger(self.__class__.__name__)

    def fetch(self, query: str, when: str = "24h") -> list[NewsEntry]:
        """
        Busca notícias no Google News para a *query* fornecida.

        Args:
            query: Termo de busca (ex.: ``'PETROBRAS'``).
            when:  Janela temporal aceita pelo Google News (ex.: ``'24h'``, ``'7d'``).

        Returns:
            Lista de :class:`NewsEntry` com título e link de cada resultado.
        """
        self._logger.info("Buscando notícias para '%s' (%s)", query, when)
        result = self._client.search(query, when=when)
        entries = [
            NewsEntry(title=item.title, link=item.link)
            for item in result.get("entries", [])
        ]
        self._logger.info("%d entradas encontradas", len(entries))
        return entries


class GoogleNewsUrlDecoder:
    """
    Implementação de :class:`UrlDecoder` usando ``googlenewsdecoder``.

    Args:
        interval: Intervalo em segundos entre tentativas de decodificação (padrão: ``1``).
    """

    def __init__(self, interval: int = 1) -> None:
        self._interval = interval
        self._logger = logging.getLogger(self.__class__.__name__)

    def decode(self, url: str) -> Optional[str]:
        """
        Decodifica a URL redirecionada do Google News para a URL real do artigo.

        Args:
            url: URL original do feed Google News.

        Returns:
            URL real do artigo, ou ``None`` se a decodificação falhar.
        """
        result = new_decoderv1(url, interval=self._interval)
        if result.get("status"):
            real_url = result["decoded_url"]
            self._logger.debug("URL decodificada: %s", real_url)
            return real_url

        self._logger.warning("Não foi possível decodificar: %s", url)
        return None


class NewspaperArticleExtractor:
    """
    Implementação de :class:`ArticleExtractor` usando a biblioteca ``newspaper3k``.

    Args:
        language: Código de idioma para processamento do artigo (padrão: ``'pt'``).
    """

    def __init__(self, language: str = "pt") -> None:
        self._language = language
        self._logger = logging.getLogger(self.__class__.__name__)

    def extract(self, url: str) -> str:
        """
        Baixa e analisa o conteúdo do artigo na *url* fornecida.

        Args:
            url: URL real do artigo.

        Returns:
            Texto extraído do artigo.

        Raises:
            Exception: Propaga qualquer erro de download ou parsing.
        """
        article = Article(url, language=self._language)
        article.download()
        article.parse()
        self._logger.debug("Artigo extraído com %d caracteres", len(article.text))
        return article.text


# ---------------------------------------------------------------------------
# Serviço de alto nível  (Open/Closed + Dependency Inversion)
# ---------------------------------------------------------------------------

class NewsCollectorService:
    """
    Orquestra a busca, decodificação e extração de artigos de notícias.

    Depende apenas de abstrações (:class:`NewsFetcher`, :class:`UrlDecoder`,
    :class:`ArticleExtractor`), tornando-se aberto para extensão e fechado
    para modificação (Open/Closed Principle).

    Args:
        fetcher:   Responsável por buscar entradas no feed de notícias.
        decoder:   Responsável por decodificar URLs redirecionadas.
        extractor: Responsável por extrair o texto de cada artigo.
        delay:     Tempo de espera (em segundos) entre o processamento de cada
                   artigo para evitar sobrecarga nas fontes (padrão: ``2``).
    """

    def __init__(
        self,
        fetcher: NewsFetcher,
        decoder: UrlDecoder,
        extractor: ArticleExtractor,
        delay: float = 2.0,
    ) -> None:
        self._fetcher = fetcher
        self._decoder = decoder
        self._extractor = extractor
        self._delay = delay
        self._logger = logging.getLogger(self.__class__.__name__)

    def collect(
        self,
        query: str,
        when: str = "24h",
        limit: int = 5,
    ) -> list[NewsArticle]:
        """
        Executa o pipeline completo: busca → decodifica URL → extrai conteúdo.

        Args:
            query: Termo de busca (ex.: ``'PETROBRAS'``).
            when:  Janela temporal do Google News (ex.: ``'24h'``, ``'7d'``).
            limit: Número máximo de artigos a processar.

        Returns:
            Lista de :class:`NewsArticle` processados com sucesso.
        """
        entries = self._fetcher.fetch(query, when)[:limit]
        articles: list[NewsArticle] = []

        for entry in entries:
            self._logger.info("Processando: %s", entry.title)
            article = self._process_entry(entry)
            if article:
                articles.append(article)
            time.sleep(self._delay)

        self._logger.info("%d artigos coletados com sucesso", len(articles))
        return articles

    # ------------------------------------------------------------------
    # Métodos privados
    # ------------------------------------------------------------------

    def _process_entry(self, entry: NewsEntry) -> Optional[NewsArticle]:
        """
        Processa uma única entrada: decodifica a URL e extrai o texto.

        Args:
            entry: Entrada bruta do feed de notícias.

        Returns:
            :class:`NewsArticle` preenchido, ou ``None`` em caso de erro.
        """
        try:
            real_url = self._decoder.decode(entry.link)
            if not real_url:
                return None

            text = self._extractor.extract(real_url)
            return NewsArticle(title=entry.title, real_url=real_url, text=text)

        except Exception as exc:  # noqa: BLE001
            self._logger.error("Erro ao processar '%s': %s", entry.title, exc)
            return None


# ---------------------------------------------------------------------------
# Ponto de entrada / exemplo de uso
# ---------------------------------------------------------------------------

def main() -> None:
    """Demonstra o uso do :class:`NewsCollectorService` com as implementações padrão."""

    service = NewsCollectorService(
        fetcher=GoogleNewsFetcher(lang="pt", country="BR"),
        decoder=GoogleNewsUrlDecoder(interval=1),
        extractor=NewspaperArticleExtractor(language="pt"),
        delay=2.0,
    )

    articles = service.collect(query="PETROBRAS", when="24h", limit=5)

    for article in articles:
        print(f"\n{'='*60}")
        print(f"Título  : {article.title}")
        print(f"URL real: {article.real_url}")
        print(f"Prévia  :\n{article.preview}")


if __name__ == "__main__":
    main()