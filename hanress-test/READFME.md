1.mcp三件套: 
    Tools ----参考OrderService
    → 我能干什么
    
    Resources----OrderResources
    → 我这里有什么东西可以读
    
    Prompts----参考FinancePrompts
    → 我这里有哪些现成的工作提示模板
2.一个标准 MCP Client 把你 Spring Boot 暴露出来的 Tool / Resource / Prompt 都看一遍，用MCP inspector
使用这个命令安装：npx @modelcontextprotocol/inspector --cli http://127.0.0.1:8080/mcp --transport http --method tools/list
例子:npx @modelcontextprotocol/inspector --cli http://127.0.0.1:8080/mcp --transport http --method tools/call --tool-name get_order_status --tool-arg orderId=1001
例子:npx @modelcontextprotocol/inspector --cli http://127.0.0.1:8080/mcp --transport http --method resources/list
例子:npx @modelcontextprotocol/inspector --cli http://127.0.0.1:8080/mcp --transport http --method resources/read --uri order://status/guide
3.如何让codex Hanress知道你的mcp？答案就是你需要进入到codex的配置文件把项目中拥有的streamable-http暴露给它
4.我写的这些skills如何让codex知道？
