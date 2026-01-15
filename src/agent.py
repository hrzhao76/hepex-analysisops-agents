import json
import asyncio
import logging
from a2a.server.tasks import TaskUpdater
from a2a.types import Message, TaskState, Part, TextPart
from a2a.utils import get_message_text, new_agent_text_message

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from tools.root_tools import inspect_root_schema_tool, load_kinematics_tool
from tools.physics_tools import calc_dilepton_mass_tool, calc_system_invariant_mass_tool
from tools.fitting_tools import fit_peak_tool
from tools.data_tools import download_atlas_data_tool, list_local_root_files_tool



logger = logging.getLogger(__name__)

class WhiteAgent:
    def __init__(self):
        self.agent = Agent(
            name="hepex_white_agent",
            model="gemini-2.5-flash",
            generate_content_config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=8192
            ),
            description="General-purpose physics analysis agent using tools.",
            instruction=(
                "You are a physics analysis agent.\n"
                "- Use provided tools; do not do low-level ROOT I/O yourself.\n"
                "- If data files are not accessible at the provided paths (e.g. running on a separate server), use download_atlas_data_tool to download them locally.\n"
                "- If schema is unknown, inspect first.\n"
                "- Make decisions explicitly and do sanity checks.\n"
                "- Output a single JSON object in the task-required format.\n"
            ),
            tools=[
                # Data access tools
                download_atlas_data_tool,
                list_local_root_files_tool,
                # ROOT analysis tools
                inspect_root_schema_tool,
                load_kinematics_tool,
                calc_dilepton_mass_tool,
                calc_system_invariant_mass_tool,
                fit_peak_tool,
            ],
        )

        self.session_service = InMemorySessionService()
        self.app_name = "hepex_analysisops"
        self.runner = Runner(
            agent=self.agent,
            app_name=self.app_name,
            session_service=self.session_service,
        )
        

    async def run(self, message: Message, updater: TaskUpdater) -> None:
        input_text = get_message_text(message)
        
        # 1. Log the received request
        try:
            req_json = json.loads(input_text)
            logger.info("Received request")
            logger.debug(f"Request payload:\n{json.dumps(req_json, indent=2)}")
            
            
            # 2. Environment/Data Check
            # Check if this is a task request with data requirements
            if isinstance(req_json, dict) and req_json.get("role") == "task_request":
                data_info = req_json.get("data", {})
                release = data_info.get("release")
                dataset = data_info.get("dataset")
                skim = data_info.get("skim")
                
                if release and dataset and skim:
                    logger.info(f"WhiteAgent: Checking data environment for {release}/{dataset}/{skim}...")
                    try:
                        # Ensure data is present locally. 
                        # This handles the case where the benchmark (Green Agent) might be on a different 
                        # machine or container, ensuring the White Agent has its own local copy/cache.
                        res = download_atlas_data_tool(
                            release=release,
                            dataset=dataset,
                            skim=skim,
                            max_files=1, # Ensure at least one file is present to start
                        )

                        #pring res 
                        logger.debug(f"WhiteAgent: Data check result: {res}")
                        
                        if res['status'] == 'ok':
                            logger.info(f"WhiteAgent: Data check passed. Local paths: {res['local_paths']}")
                        else:
                            logger.warning(f"WhiteAgent: Data check warning: {res.get('notes')}")
                    except Exception as e:
                        logger.error(f"WhiteAgent: Data check failed with error: {e}")

        except json.JSONDecodeError:
            logger.warning("Received non-JSON request")
            logger.debug(f"Raw input text:\n{input_text}")

        await updater.update_status(
            TaskState.working,
            new_agent_text_message("Running analysis agent..."),
        )

        user_id = "a2a_user"
        # Use context_id as session_id to enable multi-turn conversations
        session_id = message.context_id or message.message_id

        # Create session if it doesn't exist
        try:
            await self.session_service.create_session(
                app_name=self.app_name,
                user_id=user_id,
                session_id=session_id,
            )
        except Exception:
            # session may already exist
            pass

        content = types.Content(role="user", parts=[types.Part(text=input_text)])
        
        final_text = None
        try:
            retry_delay = 2.0
            max_retries = 5
            
            for attempt in range(max_retries):
                try:
                    async for event in self.runner.run_async(
                        user_id=user_id,
                        session_id=session_id,
                        new_message=content,
                    ):
                        if event.is_final_response():
                            if event.content and event.content.parts:
                                # Extract text from all parts, filtering to text parts only
                                text_parts = []
                                for part in event.content.parts:
                                    if hasattr(part, 'text') and part.text:
                                        text_parts.append(part.text)
                                final_text = "\n".join(text_parts) if text_parts else None
                            if not final_text:
                                final_text = event.error_message or "No final response text."
                            break
                    
                    # If we got here successfully, break out of retry loop
                    break
                    
                except Exception as e:
                    err_str = str(e)
                    is_last_attempt = (attempt == max_retries - 1)
                    # Check for rate limits (429 or RESOURCE_EXHAUSTED)
                    is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
                    
                    if is_rate_limit and not is_last_attempt:
                        logger.warning(f"WhiteAgent: Rate limit hit (429). Retrying {attempt+1}/{max_retries} in {retry_delay}s...")
                        await asyncio.sleep(retry_delay)
                        retry_delay = min(retry_delay * 2, 30.0)
                        continue
                    else:
                        # Non-retryable or retries exhausted
                        final_text = json.dumps(
                            {"status": "error", "error": f"Agent run failed: {type(e).__name__}: {e}"},
                            ensure_ascii=False,
                        )
                        break

            if final_text is None:
                final_text = json.dumps(
                    {"status": "error", "error": "No final response from runner"},
                    ensure_ascii=False,
                )

            # Add artifact BEFORE marking task as completed
            # A2A closes the stream on terminal states, so artifacts must come first
            await updater.add_artifact(
                parts=[Part(root=TextPart(kind="text", text=final_text))],
                name="submission_trace",
            )
            await updater.update_status(TaskState.completed, new_agent_text_message("Done."))

        except Exception as e:
            err = {"status": "error", "error": f"{type(e).__name__}: {e}"}
            # Add artifact BEFORE marking task as failed
            await updater.add_artifact(
                parts=[Part(root=TextPart(kind="text", text=json.dumps(err, ensure_ascii=False)))],
                name="submission_trace",
            )
            await updater.update_status(TaskState.failed, new_agent_text_message(err["error"]))