package simu.manufacturing;
import com.fasterxml.jackson.databind.*;
final class Json {
 static final ObjectMapper M=new ObjectMapper().enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);
 static JsonNode parse(String s) {try{return M.readTree(s);}catch(Exception e){throw new IllegalArgumentException("Invalid JSON");}}
 static String write(Object o){try{return M.writeValueAsString(o);}catch(Exception e){throw new IllegalArgumentException(e);}}
}
