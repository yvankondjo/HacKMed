---
name: livekit-agents
description: 'Build voice AI agents with LiveKit Cloud and the Agents SDK. Use when the user asks to "build a voice agent", "create a LiveKit agent", "add voice AI", "implement handoffs", "structure agent workflows", or is working with LiveKit Agents SDK. Provides opinionated guidance for the recommended path: LiveKit Cloud + LiveKit Inference. REQUIRES writing tests for all implementations.'
license: MIT
metadata:
  author: livekit
  version: "0.3.1"
---

# LiveKit Agents Development for LiveKit Cloud

This skill provides opinionated guidance for building voice AI agents with LiveKit Cloud. It assumes you are using LiveKit Cloud (the recommended path) and encodes *how to approach* agent development, not API specifics. All factual information about APIs, methods, and configurations must come from live documentation.

**This skill is for LiveKit Cloud developers.** If you're self-hosting LiveKit, some recommendations (particularly around LiveKit Inference) won't apply directly.

## MANDATORY: Read This Checklist Before Starting

Before writing ANY code, complete this checklist:

1. **Read this entire skill document** - Do not skip sections even if MCP is available
2. **Ensure LiveKit Cloud project is connected** - You need `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` from your Cloud project
3. **Set up documentation access** - Use MCP if available, otherwise use web search
4. **Plan to write tests** - Every agent implementation MUST include tests (see testing section below)
5. **Verify all APIs against live docs** - Never rely on model memory for LiveKit APIs

This checklist applies regardless of whether MCP is available. MCP provides documentation access but does NOT replace the guidance in this skill.

## LiveKit Cloud Setup

LiveKit Cloud is the fastest way to get a voice agent running. It provides:
- Managed infrastructure (no servers to deploy)
- **LiveKit Inference** for AI models (no separate API keys needed)
- Built-in noise cancellation, turn detection, and other voice features
- Simple credential management

### Connect to Your Cloud Project

1. Sign up at [cloud.livekit.io](https://cloud.livekit.io) if you haven't already
2. Create a project (or use an existing one)
3. Get your credentials from the project settings:
   - `LIVEKIT_URL` - Your project's WebSocket URL (e.g., `wss://your-project.livekit.cloud`)
   - `LIVEKIT_API_KEY` - API key for authentication
   - `LIVEKIT_API_SECRET` - API secret for authentication

4. Set these as environment variables (typically in `.env.local`):
```bash
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your-api-key
LIVEKIT_API_SECRET=your-api-secret
```

The LiveKit CLI can automate credential setup. Consult the CLI documentation for current commands.

### Use LiveKit Inference for AI Models

**LiveKit Inference is the recommended way to use AI models with LiveKit Cloud.** It provides access to leading AI model providers—all through your LiveKit credentials with no separate API keys needed.

Benefits of LiveKit Inference:
- No separate API keys to manage for each AI provider
- Billing consolidated through your LiveKit Cloud account
- Optimized for voice AI workloads

Consult the documentation for available models, supported providers, and current usage patterns. The documentation always has the most up-to-date information.

## Critical Rule: Never Trust Model Memory for LiveKit APIs

LiveKit Agents is a fast-evolving SDK. Model training data is outdated the moment it's created. When working with LiveKit:

- **Never assume** API signatures, method names, or configuration options from memory
- **Never guess** SDK behavior or default values
- **Always verify** against live documentation before writing code
- **Always cite** the documentation source when implementing features

This rule applies even when confident about an API. Verify anyway.

## REQUIRED: Use LiveKit MCP Server for Documentation

Before writing any LiveKit code, ensure access to the LiveKit documentation MCP server. This provides current, verified API information and prevents reliance on stale model knowledge.

### Check for MCP Availability

Look for `livekit-docs` MCP tools. If available, use them for all documentation lookups:
- Search documentation before implementing any feature
- Verify API signatures and method parameters
- Look up configuration options and their valid values
- Find working examples for the specific task at hand

### If MCP Is Not Available

If the LiveKit MCP server is not configured, inform the user and recommend installation. Installation instructions for all supported platforms are available at:

**https://docs.livekit.io/intro/mcp-server/**

Fetch the installation instructions appropriate for the user's coding agent from that page.

### Fallback When MCP Unavailable

If MCP cannot be installed in the current session:
1. **Inform the user immediately** that documentation cannot be verified in real-time
2. Use web search to fetch current documentation from docs.livekit.io
3. **Explicitly mark all LiveKit-specific code** with a comment like `# UNVERIFIED: Please check docs.livekit.io for current API`
4. **State clearly** when you cannot verify something: "I cannot verify this API signature against current documentation"
5. Recommend the user verify against https://docs.livekit.io before using the code

## Voice Agent Architecture Principles

Voice AI agents have fundamentally different requirements than text-based agents or traditional software. Internalize these principles:

### Latency Is Critical

Voice conversations are real-time. Users expect responses within hundreds of milliseconds, not seconds. Every architectural decision should consider latency impact:

- Minimize LLM context size to reduce inference time
- Avoid unnecessary tool calls during active conversation
- Prefer streaming responses over batch responses
- Design for the unhappy path (network delays, API timeouts)

### Context Bloat Kills Performance

Large system prompts and extensive tool lists directly increase latency. A voice agent with 50 tools and a 10,000-token system prompt will feel sluggish regardless of model speed.

Design agents with minimal viable context:
- Include only tools relevant to the current conversation phase
- Keep system prompts focused and concise
- Remove tools and context that aren't actively needed

### Users Don't Read, They Listen

Voice interface constraints differ from text:
- Long responses frustrate users—keep outputs concise
- Users cannot scroll back—ensure clarity on first delivery
- Interruptions are normal—design for graceful handling
- Silence feels broken—acknowledge processing when needed

## Workflow Architecture: Handoffs and Tasks

Complex voice agents should not be monolithic. LiveKit Agents supports structured workflows that maintain low latency while handling sophisticated use cases.

### The Problem with Monolithic Agents

A single agent handling an entire conversation flow accumulates:
- Tools for every possible action (bloated tool list)
- Instructions for every conversation phase (bloated context)
- State management for all scenarios (complexity)

This creates latency and reduces reliability.

### Handoffs: Agent-to-Agent Transitions

Handoffs allow one agent to transfer control to another. Use handoffs to:
- Separate distinct conversation phases (greeting → intake → resolution)
- Isolate specialized capabilities (general support → billing specialist)
- Manage context boundaries (each agent has only what it needs)

Design handoffs around natural conversation boundaries where context can be summarized rather than transferred wholesale.

### Tasks: Scoped Operations

Tasks are tightly-scoped prompts designed to achieve a specific outcome. Use tasks for:
- Discrete operations that don't require full agent capabilities
- Situations where a focused prompt outperforms a general-purpose agent
- Reducing context when only a specific capability is needed

Consult the documentation for implementation details on handoffs and tasks.

## REQUIRED: Write Tests for Agent Behavior

Voice agent behavior is code. Every agent implementation MUST include tests. Shipping an agent without tests is shipping untested code.

### Mandatory Testing Workflow

When building or modifying a LiveKit agent:

1. **Create a `tests/` directory** if one doesn't exist
2. **Write at least one test** before considering the implementation complete
3. **Test the core behavior** the user requested
4. **Run the tests** to verify they pass

### Test-Driven Development Process

When modifying agent behavior—instructions, tool descriptions, workflows—begin by writing tests for the desired behavior:

1. Define what the agent should do in specific scenarios
2. Write test cases that verify this behavior
3. Implement the feature
4. Iterate until tests pass

This approach prevents shipping agents that "seem to work" but fail in production.

### What Every Agent Test Should Cover

At minimum, write tests for:
- **Basic conversation flow**: Agent responds appropriately to a greeting
- **Tool invocation** (if tools exist): Tools are called with correct parameters
- **Error handling**: Agent handles unexpected input gracefully

Focus tests on:
- **Tool invocation**: Does the agent call the right tools with correct parameters?
- **Response quality**: Does the agent produce appropriate responses for given inputs?
- **Workflow transitions**: Do handoffs and tasks trigger correctly?
- **Edge cases**: How does the agent handle unexpected input, interruptions, silence?

### Test Implementation Pattern

Use LiveKit's testing framework. Consult the testing documentation via MCP for current patterns:
```
search: "livekit agents testing"
```

The framework supports:
- Simulated user input
- Verification of agent responses
- Tool call assertions
- Workflow transition testing

### Why This Is Non-Negotiable

Agents that "seem to work" in manual testing frequently fail in production:
- Prompt changes silently break behavior
- Tool descriptions affect when tools are called
- Model updates change response patterns

Tests catch these issues before users do.

### Skipping Tests

If a user explicitly requests no tests, proceed without them but inform them:
> "I've built the agent without tests as requested. I strongly recommend adding tests before deploying to production. Voice agents are difficult to verify manually and tests prevent silent regressions."

## Common Mistakes to Avoid

### Overloading the Initial Agent

Starting with one agent that "does everything" and adding tools/instructions over time. Instead, design workflow structure upfront, even if initial implementation is simple.

### Ignoring Latency Until It's a Problem

Latency issues compound. An agent that feels "a bit slow" in development becomes unusable in production with real network conditions. Measure and optimize latency continuously.

### Copying Examples Without Understanding

Examples in documentation demonstrate specific patterns. Copying code without understanding its purpose leads to bloated, poorly-structured agents. Understand what each component does before including it.

### Skipping Tests Because "It's Just Prompts"

Agent behavior is code. Prompt changes affect behavior as much as code changes. Test agent behavior with the same rigor as traditional software. **Never deliver an agent implementation without at least one test file.**

### Assuming Model Knowledge Is Current

Reiterating the critical rule: never trust model memory for LiveKit APIs. The SDK evolves faster than model training cycles. Verify everything.

## When to Consult Documentation

**Always consult documentation for:**
- API method signatures and parameters
- Configuration options and their valid values
- SDK version-specific features or changes
- Deployment and infrastructure setup
- Model provider integration details
- CLI commands and flags

**This skill provides guidance on:**
- Architectural approach and design principles
- Workflow structure decisions
- Testing strategy
- Common pitfalls to avoid

The distinction matters: this skill tells you *how to think* about building voice agents. The documentation tells you *how to implement* specific features.

## Feedback Loop

When using LiveKit documentation via MCP, note any gaps, outdated information, or confusing content. Reporting documentation issues helps improve the ecosystem for all developers.

## Summary

Building effective voice agents with LiveKit Cloud requires:

1. **Use LiveKit Cloud + LiveKit Inference** as the foundation—it's the fastest path to production
2. **Verify everything** against live documentation—never trust model memory
3. **Minimize latency** at every architectural decision point
4. **Structure workflows** using handoffs and tasks to manage complexity
5. **Test behavior** before and after changes—never ship without tests
6. **Keep context minimal**—only include what's needed for the current phase

These principles remain valid regardless of SDK version or API changes. For all implementation specifics, consult the LiveKit documentation via MCP.


# Freshness Rules for LiveKit Development

This document provides detailed guidance on maintaining accuracy when building with LiveKit Agents. These rules exist because model training data becomes outdated immediately, and LiveKit's SDK evolves rapidly.

## The Core Problem

Coding agents (Claude, GPT, etc.) are trained on historical data. This training includes:
- Old versions of LiveKit documentation
- Outdated code examples from blogs and tutorials
- Previous SDK versions with different APIs
- Community answers that may no longer be accurate

When an agent "knows" something about LiveKit, that knowledge may be months or years out of date.

## Verification Requirements

### Before Writing Any LiveKit Code

1. **Identify what needs verification**
   - Method names and signatures
   - Configuration options and their types
   - Import paths and module structure
   - Default values and behaviors

2. **Query the documentation**
   - Use MCP to search for the specific feature
   - Read the current documentation, not cached knowledge
   - Look for version notes or recent changes

3. **Cite your source**
   - Note which documentation page informed the implementation
   - If something cannot be verified, explicitly state this

### During Implementation

When writing code, verify:

| Element | Why It Changes | How to Verify |
|---------|----------------|---------------|
| Import statements | Module restructuring | Search docs for current import paths |
| Method signatures | API evolution | Look up method in API reference |
| Configuration keys | Naming conventions change | Check configuration documentation |
| Default behaviors | Defaults are tuned over time | Read parameter documentation |
| Event names | Event systems evolve | Check events/callbacks documentation |

### After Implementation

Before presenting code to the user:
- Confirm all APIs used are documented
- Verify example patterns match current best practices
- Check for deprecation warnings in documentation

## What Cannot Be Verified

Some things legitimately cannot be verified against documentation:
- User's specific environment or configuration
- Integration with user's existing codebase
- Business logic and application requirements

When providing guidance on these topics, clearly distinguish between:
- "According to LiveKit documentation..." (verified)
- "Based on your requirements..." (application-specific)
- "This may need adjustment..." (uncertain)

## Red Flags: When to Stop and Verify

Pause and verify against documentation when:

1. **Writing from memory** - If you're typing an API call without having just looked it up, verify it
2. **"I think" or "I believe"** - Uncertainty about LiveKit APIs requires verification
3. **Complex configurations** - Multi-option configurations are likely to have evolved
4. **Error handling** - Exception types and error formats change
5. **Newer features** - Recently added features have the highest drift risk

## Communication with Users

### When Verified

```
According to the LiveKit Agents documentation, the correct approach is...
[implementation]
```

### When Partially Verified

```
The workflow structure follows LiveKit's documented patterns. However, I could not
verify [specific detail] against current documentation. Please confirm this matches
your SDK version.
```

### When Unverified

```
I cannot verify this implementation against current LiveKit documentation. This is
based on general patterns and may require adjustment. I recommend:
1. Checking the official documentation at [link]
2. Testing this implementation before relying on it
```

## MCP Server Unavailable

If the LiveKit MCP server is not installed or accessible:

1. **Inform the user immediately** - They should know verification isn't possible
2. **Recommend installation** - Point to https://docs.livekit.io/mcp
3. **Proceed with caution** - Clearly mark all LiveKit-specific code as unverified
4. **Suggest manual verification** - User should check docs before using the code

Do not pretend to have verified something when MCP access was unavailable.

## Version Awareness

LiveKit Agents has distinct versions with potentially different APIs:
- Python SDK (`livekit-agents`)
- Node.js/TypeScript SDK (`@livekit/agents`)

Each has its own release cycle and API surface. When working with LiveKit:
- Determine which SDK the user is using
- Search documentation specific to that SDK
- Do not assume API parity between Python and Node.js versions

## Examples of Drift

These examples illustrate why verification matters:

### Configuration Changes
Old tutorials might show:
```python
agent = VoiceAgent(config={"model": "gpt-4"})
```

Current API might be:
```python
agent = VoiceAgent(llm=SomeLLMClass(...))
```

### Method Renames
What was once:
```python
agent.start_session()
```

Might now be:
```python
agent.start()
```

### Import Restructuring
Previous:
```python
from livekit.agents.voice import VoiceAgent
```

Current:
```python
from livekit.agents import VoiceAgent
```

None of these changes are predictable from training data. Only live documentation reflects current state.

## Summary

1. **Default to distrust** - Assume any LiveKit knowledge from memory is outdated
2. **Verify actively** - Use MCP to check documentation before implementation
3. **Communicate uncertainty** - Tell users when something cannot be verified
4. **Cite sources** - Reference documentation when providing verified information
5. **Recommend MCP** - If unavailable, make installation a priority
