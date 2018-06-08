<?php

namespace Emipro\Apichange\Model;

use Emipro\Apichange\Api\StockInterface;
use Magento\Catalog\Model\ProductFactory;

/**
 * Defines the implementaiton class of the calculator service contract.
 */
class Stock implements StockInterface
{
    protected $productFactory;

    public function __construct(
        ProductFactory $productFactory,
        \Magento\CatalogInventory\Api\StockRegistryInterface $stockRegistry
    ) {
        $this->productFactory = $productFactory;
        $this->stockRegistry = $stockRegistry;
    }
    public function update($skuData)
    {
        $ary_response = [];
        foreach ($skuData as $value) {
            $productSku = $value->getSku();
            $qty = $value->getQty();
            $productId = $this->resolveProductId($productSku);
            if (is_numeric($productId)) {
                if (is_numeric($qty)) {
                    $stockItem = $this->stockRegistry->getStockItemBySku($productSku);
                    $stockItem->setQty($qty);
                    $stockItem->setIsInStock((bool) $qty);
                    $this->stockRegistry->updateStockItemBySku($productSku, $stockItem);
                    $valid = ["code" => "200", "message" => "Stock Updated Of " . $productSku . " SKU On Magento"];
                    $ary_response[] = $valid;
                } else {
                    $valid = ["code" => "300", "message" => "Qty value shoud be in integer " . $productSku];
                    $ary_response[] = $valid;
                }
                //return $valid;
            } else {
                //return $productId;
                $ary_response[] = $productId;
            }
        }
        return $ary_response;
    }

    /**
     * @param string $productSku
     * @return int
     * @throws \Magento\Framework\Exception\NoSuchEntityException
     */
    protected function resolveProductId($productSku)
    {
        $product = $this->productFactory->create();
        $productId = $product->getIdBySku($productSku);
        if (!$productId) {
            $invalid = ["code" => '301', "message" => "SKU " . $productSku . " Not Found On Magento"];
            return $invalid;
        }
        return $productId;
    }
}
