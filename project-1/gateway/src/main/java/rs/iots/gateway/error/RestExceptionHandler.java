package rs.iots.gateway.error;

import io.grpc.Status;
import io.grpc.StatusRuntimeException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import rs.iots.gateway.dto.ErrorDto;

import java.time.Instant;
import java.util.stream.Collectors;

@RestControllerAdvice
public class RestExceptionHandler {

    @ExceptionHandler(StatusRuntimeException.class)
    public ResponseEntity<ErrorDto> grpc(StatusRuntimeException ex) {
        Status.Code code = ex.getStatus().getCode();
        HttpStatus http = switch (code) {
            case NOT_FOUND -> HttpStatus.NOT_FOUND;
            case INVALID_ARGUMENT, OUT_OF_RANGE -> HttpStatus.BAD_REQUEST;
            case ALREADY_EXISTS -> HttpStatus.CONFLICT;
            case UNAVAILABLE, DEADLINE_EXCEEDED -> HttpStatus.SERVICE_UNAVAILABLE;
            default -> HttpStatus.BAD_GATEWAY;
        };
        String msg = ex.getStatus().getDescription() == null
                ? code.name() : ex.getStatus().getDescription();
        return build(http, msg);
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ErrorDto> validation(MethodArgumentNotValidException ex) {
        String msg = ex.getBindingResult().getFieldErrors().stream()
                .map(f -> f.getField() + ": " + f.getDefaultMessage())
                .collect(Collectors.joining("; "));
        return build(HttpStatus.BAD_REQUEST, msg);
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ErrorDto> generic(Exception ex) {
        return build(HttpStatus.INTERNAL_SERVER_ERROR, ex.getMessage());
    }

    private ResponseEntity<ErrorDto> build(HttpStatus status, String message) {
        return ResponseEntity.status(status)
                .body(new ErrorDto(Instant.now(), status.value(),
                        status.getReasonPhrase(), message));
    }
}
