# def test_white_agent_uses_openai_litellm_by_default(monkeypatch):
#     import agent as agent_module

#     created = {}

#     class DummyLiteLlm:
#         def __init__(self, *, model):
#             created["litellm_model"] = model
#             self.model = model

#     class DummyAgent:
#         def __init__(self, **kwargs):
#             created["agent_kwargs"] = kwargs

#     class DummyRunner:
#         def __init__(self, **kwargs):
#             created["runner_kwargs"] = kwargs

#     class DummySessionService:
#         pass

#     monkeypatch.setenv("HEPEX_OPENAI_MODEL", "openai/gpt-5")
#     monkeypatch.delenv("HEPEX_AGENT_MODEL", raising=False)
#     monkeypatch.setattr(agent_module, "LiteLlm", DummyLiteLlm)
#     monkeypatch.setattr(agent_module, "Agent", DummyAgent)
#     monkeypatch.setattr(agent_module, "Runner", DummyRunner)
#     monkeypatch.setattr(agent_module, "InMemorySessionService", DummySessionService)

#     white_agent = agent_module.WhiteAgent()

#     assert created["litellm_model"] == "openai/gpt-5"
#     assert created["agent_kwargs"]["model"].model == "openai/gpt-5"
#     assert created["runner_kwargs"]["agent"] is white_agent.agent


# def test_hepex_agent_model_override_wins(monkeypatch):
#     import agent as agent_module

#     created = {}

#     class DummyLiteLlm:
#         def __init__(self, *, model):
#             created["litellm_model"] = model
#             self.model = model

#     class DummyAgent:
#         def __init__(self, **kwargs):
#             created["agent_kwargs"] = kwargs

#     class DummyRunner:
#         def __init__(self, **kwargs):
#             created["runner_kwargs"] = kwargs

#     class DummySessionService:
#         pass

#     monkeypatch.setenv("HEPEX_OPENAI_MODEL", "openai/gpt-5")
#     monkeypatch.setenv("HEPEX_AGENT_MODEL", "openai/gpt-5-mini")
#     monkeypatch.setattr(agent_module, "LiteLlm", DummyLiteLlm)
#     monkeypatch.setattr(agent_module, "Agent", DummyAgent)
#     monkeypatch.setattr(agent_module, "Runner", DummyRunner)
#     monkeypatch.setattr(agent_module, "InMemorySessionService", DummySessionService)

#     agent_module.WhiteAgent()

#     assert created["litellm_model"] == "openai/gpt-5-mini"
