import random
import sys

def quadratic_a(point, vertex):
    return (point[1]-vertex[1])/(-vertex[0]+point[0])**2

def expand(text):
    for c, _ in enumerate(text, 1):
        yield (' '*c).join(list(text))
    yield (' '*(len(text)+1)).join(list(text))
    for c, _ in reversed(list(enumerate(text, 1))):
        yield (' '*c).join(list(text))


def converge(text):
    if len(text) % 2 == 0:
        index = int(len(text)/2)
        text = text[:index] + " " + text[index:]
    number_of_parabolas = len(text)//2
    parabola_params = []
    result = []
    for i in range(1, number_of_parabolas+1):
        p = len(text)
        q = i
        a = quadratic_a((1, i*(len(text)+1)), (p, q))
        parabola_params.append({"p":p, "q":q, "a":a})
    for i in range(1, (len(text))*2):
        chars = [" "] * (len(text) + ((len(text)-1)*len(text)))
        for c, v in enumerate(reversed(text[:len(text)//2])):
            params = parabola_params[c]
            chars[len(chars)//2 - round(params["a"] * (i - params["p"])**2 + params["q"])] = v
            # yield round(params["a"] * (i - params["p"]) + params["q"])
        chars[len(chars)//2] = text[len(text)//2]
        for c, v in enumerate(text[len(text)//2+1:]):
            params = parabola_params[c]
            chars[len(chars)//2 + round(params["a"] * (i - params["p"])**2 + params["q"])] = v
            # yield round(params["a"] * (i - params["p"]) + params["q"])
        result.append("".join(chars))
    return result
        
    
if __name__ == "__main__":
    if len(sys.argv) == 1:
        text = "testing"
    else:
        text = sys.argv[1]
    for i in converge(text):
        print(i)