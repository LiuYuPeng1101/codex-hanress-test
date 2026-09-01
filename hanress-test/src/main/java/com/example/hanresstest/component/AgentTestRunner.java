//package com.example.hanresstest.component;
//
//
//
//import org.springframework.boot.CommandLineRunner;
//import org.springframework.stereotype.Component;
//
//@Component
//public class AgentTestRunner implements CommandLineRunner {
//
//    private final CodexAppServerClient codexClient;
//
//    public AgentTestRunner(
//            CodexAppServerClient codexClient
//    ) {
//        this.codexClient = codexClient;
//    }
//
//    @Override
//    public void run(String... args)
//            throws Exception {
//
//        codexClient.start();
//
//        String threadId =
//                codexClient
//                        .startThread()
//                        .get();
//
//        System.out.println(
//                "✅ Thread = " + threadId
//        );
//
//        String turnId =
//                codexClient
//                        .startTurn(
//                                threadId,
//                                """
//                                请查询订单1001当前的订单状态，
//                                并告诉我预计送达日期。
//
//                                必须使用 get_order_status 工具获取真实订单数据，
//                                不要自己猜测。
//                                """
//                        )
//                        .get();
//
//        System.out.println(
//                "✅ Turn = " + turnId
//        );
//    }
//}
