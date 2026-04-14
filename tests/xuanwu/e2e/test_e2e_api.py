# -*- coding: utf-8 -*-
"""
E2E API 测试

测试完整的 API 端到端流程，需要启动完整服务。
运行方式:
1. 设置环境变量: ANTHROPIC_BASE_URL, ANTHROPIC_API_KEY
2. pytest -m e2e tests/xuanwu/test_e2e_api.py -v
"""

import os
import asyncio
import pytest
import pytest_asyncio
from typing import AsyncGenerator

import httpx


# 标记为 e2e 测试
pytestmark = pytest.mark.e2e


# 测试服务地址
TEST_SERVER_URL = os.environ.get("TEST_SERVER_URL", "http://127.0.0.1:9000")


@pytest.fixture(scope="module")
def event_loop():
    """创建事件循环"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """HTTP 客户端 fixture"""
    async with httpx.AsyncClient(base_url=TEST_SERVER_URL, timeout=60.0) as c:
        try:
            await c.get("/api/health")
        except httpx.HTTPError:
            pytest.skip(f"E2E server is not reachable at {TEST_SERVER_URL}")
        yield c


class TestHealthAPI:
    """健康检查 API 测试"""

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client: httpx.AsyncClient):
        """测试健康检查端点"""
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        
        data = resp.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data


class TestSkillsAPI:
    """Skills API 测试"""

    @pytest.mark.asyncio
    async def test_list_skills(self, client: httpx.AsyncClient):
        """测试 skills 接口在鉴权开关下的兼容行为。"""
        resp = await client.get("/api/skills")
        assert resp.status_code in (200, 401)
        if resp.status_code == 200:
            payload = resp.json()
            skills = payload if isinstance(payload, list) else payload.get("skills", [])
            assert isinstance(skills, list)


    @pytest.mark.asyncio
    async def test_skills_contain_builtin_tools(self, client: httpx.AsyncClient):
        """测试 skills 接口在匿名模式下可返回工具列表。"""
        resp = await client.get("/api/skills")
        assert resp.status_code in (200, 401)
        if resp.status_code == 200:
            payload = resp.json()
            skills = payload if isinstance(payload, list) else payload.get("skills", [])
            skill_names = {item.get("name", "") for item in skills if isinstance(item, dict)}
            assert "present_files" in skill_names


class TestErrorHandling:
    """错误处理测试"""

    @pytest.mark.asyncio
    async def test_invalid_endpoint(self, client: httpx.AsyncClient):
        """测试无效端点在鉴权开关下返回 401 或 404。"""
        resp = await client.get("/api/nonexistent")
        assert resp.status_code in (401, 404)



if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "e2e"])
