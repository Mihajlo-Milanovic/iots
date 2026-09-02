package rs.iots.gateway.client;

import io.grpc.ManagedChannel;
import io.grpc.ManagedChannelBuilder;
import jakarta.annotation.PreDestroy;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import rs.iots.datamanager.v1.ReadingServiceGrpc;

import java.util.concurrent.TimeUnit;

@Configuration
public class GrpcConfig {

    private ManagedChannel channel;

    @Bean
    public ManagedChannel dataManagerChannel(
            @Value("${datamanager.host:localhost}") String host,
            @Value("${datamanager.port:50051}") int port) {
        channel = ManagedChannelBuilder.forAddress(host, port)
                .usePlaintext()
                .build();
        return channel;
    }

    @Bean
    public ReadingServiceGrpc.ReadingServiceBlockingStub blockingStub(ManagedChannel channel) {
        return ReadingServiceGrpc.newBlockingStub(channel);
    }

    @Bean
    public ReadingServiceGrpc.ReadingServiceStub asyncStub(ManagedChannel channel) {
        return ReadingServiceGrpc.newStub(channel);
    }

    @PreDestroy
    public void shutdown() throws InterruptedException {
        if (channel != null) {
            channel.shutdown().awaitTermination(5, TimeUnit.SECONDS);
        }
    }
}
