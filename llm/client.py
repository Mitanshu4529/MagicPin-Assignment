"""
Universal LLM client supporting multiple providers with fallback capability.
Providers: OpenAI, Anthropic, Gemini, DeepSeek, Groq, Ollama, OpenRouter.
"""

from __future__ import annotations

import json
import os
import urllib.request as urlrequest
import urllib.error as urlerror
from typing import Optional, Dict, Any

DEFAULT_TIMEOUT = 25


class LLMClient:
    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "").lower()
        self.api_key = (
            os.getenv("LLM_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("GROQ_API_KEY")
            or os.getenv("OPENROUTER_API_KEY")
            or ""
        )
        self.model = os.getenv("LLM_MODEL", "")
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")

        # Auto-detect provider from available environment variables if not explicitly specified
        if not self.provider:
            if os.getenv("ANTHROPIC_API_KEY"):
                self.provider = "anthropic"
            elif os.getenv("OPENAI_API_KEY"):
                self.provider = "openai"
            elif os.getenv("DEEPSEEK_API_KEY"):
                self.provider = "deepseek"
            elif os.getenv("GEMINI_API_KEY"):
                self.provider = "gemini"
            elif os.getenv("GROQ_API_KEY"):
                self.provider = "groq"
            elif os.getenv("OPENROUTER_API_KEY"):
                self.provider = "openrouter"

    def is_available(self) -> bool:
        if not self.provider:
            return False
        if self.provider == "ollama":
            return True
        return bool(self.api_key)

    def complete(self, prompt: str, system: Optional[str] = None, max_tokens: int = 1000, temperature: float = 0.0) -> Optional[str]:
        if not self.is_available():
            return None

        try:
            if self.provider == "openai":
                return self._call_openai(prompt, system, max_tokens, temperature)
            elif self.provider == "anthropic":
                return self._call_anthropic(prompt, system, max_tokens, temperature)
            elif self.provider == "gemini":
                return self._call_gemini(prompt, system, max_tokens, temperature)
            elif self.provider == "deepseek":
                return self._call_deepseek(prompt, system, max_tokens, temperature)
            elif self.provider == "groq":
                return self._call_groq(prompt, system, max_tokens, temperature)
            elif self.provider == "ollama":
                return self._call_ollama(prompt, system, max_tokens, temperature)
            elif self.provider == "openrouter":
                return self._call_openrouter(prompt, system, max_tokens, temperature)
            return None
        except Exception:
            return None

    def _call_openai(self, prompt: str, system: Optional[str], max_tokens: int, temperature: float) -> str:
        model = self.model or "gpt-4o-mini"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body = json.dumps({
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }).encode("utf-8")

        req = urlrequest.Request(
            "https://api.openai.com/v1/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        )
        resp = urlrequest.urlopen(req, timeout=DEFAULT_TIMEOUT)
        data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

    def _call_anthropic(self, prompt: str, system: Optional[str], max_tokens: int, temperature: float) -> str:
        model = self.model or "claude-3-5-sonnet-20241022"
        body_dict = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}]
        }
        if system:
            body_dict["system"] = system

        req = urlrequest.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(body_dict).encode("utf-8"),
            headers={"x-api-key": self.api_key, "Content-Type": "application/json", "anthropic-version": "2023-06-01"}
        )
        resp = urlrequest.urlopen(req, timeout=DEFAULT_TIMEOUT)
        data = json.loads(resp.read().decode("utf-8"))
        return data["content"][0]["text"]

    def _call_gemini(self, prompt: str, system: Optional[str], max_tokens: int, temperature: float) -> str:
        model = self.model or "gemini-1.5-flash"
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        body = json.dumps({
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}
        }).encode("utf-8")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
        req = urlrequest.Request(url, data=body, headers={"Content-Type": "application/json"})
        resp = urlrequest.urlopen(req, timeout=DEFAULT_TIMEOUT)
        data = json.loads(resp.read().decode("utf-8"))
        return data["candidates"][0]["content"]["parts"][0]["text"]

    def _call_deepseek(self, prompt: str, system: Optional[str], max_tokens: int, temperature: float) -> str:
        model = self.model or "deepseek-chat"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        req = urlrequest.Request(
            "https://api.deepseek.com/v1/chat/completions",
            data=json.dumps({"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        )
        resp = urlrequest.urlopen(req, timeout=DEFAULT_TIMEOUT)
        data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

    def _call_groq(self, prompt: str, system: Optional[str], max_tokens: int, temperature: float) -> str:
        model = self.model or "llama-3.1-70b-versatile"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        req = urlrequest.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps({"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        )
        resp = urlrequest.urlopen(req, timeout=DEFAULT_TIMEOUT)
        data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

    def _call_ollama(self, prompt: str, system: Optional[str], max_tokens: int, temperature: float) -> str:
        model = self.model or "llama3"
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        req = urlrequest.Request(
            f"{self.ollama_url}/api/generate",
            data=json.dumps({"model": model, "prompt": full_prompt, "stream": False, "options": {"temperature": temperature}}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        resp = urlrequest.urlopen(req, timeout=DEFAULT_TIMEOUT)
        data = json.loads(resp.read().decode("utf-8"))
        return data["response"]

    def _call_openrouter(self, prompt: str, system: Optional[str], max_tokens: int, temperature: float) -> str:
        model = self.model or "anthropic/claude-3-haiku"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        req = urlrequest.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps({"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "HTTP-Referer": "https://magicpin.com"}
        )
        resp = urlrequest.urlopen(req, timeout=DEFAULT_TIMEOUT)
        data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]


global_llm_client = LLMClient()
