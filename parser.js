
$(".preu_mercat").map((key, div) => {
    div = $(div);
    let obj = {};
    obj.location = div.find(".titol")[0].innerHTML;
    let priceSpan = div.find(".preu")[0];
    if(priceSpan) obj.price = priceSpan.innerHTML; 
    else return null;

    let currSpan = div.find(".moneda")[0];
    if(currSpan) obj.currency = currSpan.innerHTML; 
    let dateSpan = div.find(".data")[0];
    if(currSpan) obj.date = dateSpan.innerHTML; 
    return obj;
});
