package rs.iots.gateway;

import io.swagger.v3.oas.annotations.OpenAPIDefinition;
import io.swagger.v3.oas.annotations.info.Info;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
@OpenAPIDefinition(info = @Info(
        title = "IoTS Gateway API",
        version = "1.0.0",
        description = "REST API za CRUD i agregacije nad očitavanjima IoT senzora. "
                + "Podaci se čuvaju preko DataManager gRPC mikroservisa (PostgreSQL)."))
public class GatewayApplication {
    public static void main(String[] args) {
        SpringApplication.run(GatewayApplication.class, args);
    }
}
